"""
Verify every provider against its LIVE endpoint.

Why this exists
---------------
The providers added from the master list were written against published API
documentation and the usual shape of bank rate pages. Not one of them could be
tested against a real response: the environment they were written in blocks
every provider host at the network policy level.

So the request shapes, the JSON field names, and above all the HTML selectors
in `providers/scrapers/sites.py` are INFORMED GUESSES. This script is how you
find out which ones are right.

Run it from a network that can reach the providers, with whatever credentials
you have:

    cd backend
    python -m scripts.verify_providers --corridor AUD:INR --amount 1000
    python -m scripts.verify_providers --corridor INR:AUD --amount 100000
    python -m scripts.verify_providers --all-corridors

For each provider it reports one of:

    OK           a plausible quote came back — check the numbers against the
                 provider's own website before trusting them
    NO KEY       credentials not configured; nothing to test yet
    N/A          does not serve this corridor or this amount (expected)
    NEEDS JS     the rate lives behind a JavaScript calculator; it needs the
                 calculator's JSON endpoint or Playwright, not a selector fix
    UNREACHABLE  the host was never reached — egress policy, DNS, or a dead
                 connection. NOTHING about this provider was verified, and no
                 edit to its parser or selectors can change that
    BROKEN       reached the provider and could not parse the answer — this is
                 the one to fix, and the error says where

UNREACHABLE is separate from BROKEN on purpose
----------------------------------------------
Both used to report as BROKEN, and that made the report actively misleading.
A corporate proxy that denies CONNECT answers `403 Forbidden`, which httpx
raises as `ProxyError('403 Forbidden')` and every provider here catches and
reports as its own error string. It is indistinguishable, by eye, from a
provider genuinely answering HTTP 403 — so a whole run of "403 Forbidden"
under a blanket "fix the selectors in sites.py" sends you to edit files that
were never the problem. The connection never left the building.

So before calling a failure BROKEN, this script checks whether the provider's
host is reachable at all, and says which it is.

Exit status
-----------
    0  nothing broken, nothing unreachable
    1  at least one provider BROKEN — a real parse failure to fix
    2  nothing broken, but at least one provider was never reached, so this
       run verified less than it looks like it did

Both 1 and 2 are non-zero so this can gate a deploy: a gate that goes green
having verified nothing is worse than one that goes red. Pass
`--allow-unreachable` to accept 0 when you already know the network is
restricted and only want the parse failures to count.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from decimal import Decimal
from typing import Dict, List, Tuple
from urllib.parse import urlparse

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from money import D, quantize_money                       # noqa: E402
from providers import ALL_PROVIDERS, select_providers      # noqa: E402
from providers.quote import RawQuote                       # noqa: E402

#: Corridors the provider master list actually targets.
DEFAULT_CORRIDORS = [("AUD", "INR"), ("INR", "AUD")]

GREEN, RED, YELLOW, BLUE, DIM, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[34m", "\033[2m", "\033[0m"
)

#: How long to wait when checking whether a host answers at all.
REACHABILITY_TIMEOUT = 10

#: Transport failures that mean the connection never got established. Anything
#: else (a reset mid-response, a protocol error) means we DID reach the host,
#: so it stays a real failure rather than being excused as a network problem.
UNREACHABLE_ERRORS = (
    httpx.ConnectError,      # DNS failure, refused, TLS handshake refused
    httpx.ConnectTimeout,    # filtered / blackholed
    httpx.ProxyError,        # egress policy denied CONNECT
)

#: host -> (reachable, why not). Probed once per run, not once per provider.
_reachability: Dict[str, Tuple[bool, str]] = {}
_reachability_lock = asyncio.Lock()


def colour(text: str, code: str) -> str:
    return text if not sys.stdout.isatty() else f"{code}{text}{RESET}"


def candidate_urls(provider) -> List[str]:
    """
    Every URL this provider might call, best guess first.

    Providers do not expose "the host I just tried" — they catch their own
    transport errors and return an error string. So the hosts are read off the
    provider instead: the scraper's configured page, the partner API's
    resolved endpoint (which honours its env override), any `*_URL` class
    constant, and the marketing site as a last resort.
    """
    urls: List[str] = []

    config = getattr(provider, "config", None)
    if config is not None and isinstance(getattr(config, "url", None), str):
        urls.append(config.url)

    # Partner APIs resolve an env override before falling back to the
    # documented URL; ask for the one that would actually be called.
    endpoint = getattr(provider, "endpoint", None)
    if callable(endpoint):
        try:
            resolved = endpoint()
        except Exception:
            resolved = None          # no published endpoint — nothing to probe
        if isinstance(resolved, str):
            urls.append(resolved)

    for attr in sorted(dir(type(provider))):
        if not attr.isupper() or not attr.endswith("URL"):
            continue
        value = getattr(type(provider), attr, None)
        if isinstance(value, str):
            urls.append(value)

    if provider.meta.website:
        urls.append(provider.meta.website)

    seen, out = set(), []
    for url in urls:
        if not url.startswith(("http://", "https://")):
            continue
        host = urlparse(url).hostname
        if host and host not in seen:
            seen.add(host)
            out.append(url)
    return out


async def host_reachable(url: str) -> Tuple[bool, str]:
    """
    Can we open a connection to this URL's host at all?

    Any HTTP answer counts as reachable, including 403 and 404: the point is
    whether the bytes got there, not whether the provider liked them. A
    provider that answers 403 to our headers is a real problem with a real
    fix; a proxy that answers 403 to CONNECT is not the provider at all.
    """
    host = urlparse(url).hostname or url

    async with _reachability_lock:
        cached = _reachability.get(host)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(
            timeout=REACHABILITY_TIMEOUT, follow_redirects=False
        ) as client:
            await client.head(f"https://{host}/")
        result = (True, "")
    except UNREACHABLE_ERRORS as e:
        result = (False, f"{type(e).__name__}: {e}")
    except httpx.HTTPError:
        # Reached it and something else went wrong (reset, protocol error).
        # That is the provider's behaviour, not the network's.
        result = (True, "")
    except Exception as e:                       # pragma: no cover - defensive
        result = (False, f"{type(e).__name__}: {e}")

    async with _reachability_lock:
        _reachability.setdefault(host, result)
    return result


async def classify_failure(provider, detail: str) -> Tuple[str, str]:
    """
    Decide whether a failed provider is UNREACHABLE or genuinely BROKEN.

    Checked by probing the host rather than by matching the error text: the
    error text for an egress denial and for a provider's own 403 are the same
    words, and guessing from them is how the two got conflated in the first
    place.
    """
    urls = candidate_urls(provider)
    if not urls:
        # Nothing to probe (a partner API with no published endpoint). Its own
        # error already says so; do not invent a network excuse for it.
        return ("BROKEN", detail)

    last_why = "no reason recorded"
    for url in urls:
        reachable, why = await host_reachable(url)
        if reachable:
            return ("BROKEN", detail)
        last_why = why

    host = urlparse(urls[0]).hostname
    return (
        "UNREACHABLE",
        f"{host} not reachable from here ({last_why}) — nothing was verified. "
        f"Provider reported: {detail}",
    )


async def probe(provider, amount: Decimal, send: str, receive: str) -> Tuple[str, str]:
    """Return (status, detail) for one provider on one corridor."""
    if not provider.meta.supports(send, receive):
        return ("N/A", f"serves {', '.join('->'.join(c) for c in provider.meta.corridors)}")

    accepted, why = provider.meta.accepts_amount(amount, send)
    if not accepted:
        return ("N/A", why)

    if provider.meta.needs_browser:
        # Checked before calling, so a genuinely dead URL on one of these can
        # still be reported as BROKEN by whatever eventually replaces the
        # stub — rather than every error being excused as "needs JS".
        return (
            "NEEDS JS",
            "rate is behind a JavaScript calculator — find the JSON endpoint "
            "it calls (as the Western Union provider does) or use Playwright",
        )

    missing = provider.meta.missing_credentials
    if missing:
        return ("NO KEY", f"set {', '.join(missing)}")

    try:
        raw: RawQuote = await provider.fetch_raw_quote(amount, send, receive)
    except Exception as e:
        return await classify_failure(provider, f"{type(e).__name__}: {e}")

    if raw.error:
        # The provider was called, so this is a failure rather than a skip —
        # but "called" is not "reached". Relabelling every error from a
        # JS-backed provider as "NEEDS JS" would mean a dead URL could never
        # fail the deploy gate; calling an egress denial BROKEN would send
        # someone to fix a selector that was never wrong.
        return await classify_failure(provider, raw.error)

    if raw.reference_only:
        return ("OK", f"mid-market reference {raw.mid_market_rate}")

    if not raw.ok:
        return ("BROKEN", "returned a quote with no usable rate")

    receive_amount = quantize_money(raw.principal * raw.exchange_rate, receive)
    eta = (
        f"{raw.eta_min_minutes}-{raw.eta_max_minutes} min"
        if raw.eta_min_minutes is not None else "no ETA"
    )
    return (
        "OK",
        f"rate {raw.exchange_rate}  fee {raw.fee} {send}  "
        f"-> {receive_amount} {receive}  ({eta}, {len(raw.options) or 1} option(s))",
    )


async def run(
    corridors: List[Tuple[str, str]],
    amount: Decimal,
    allow_unreachable: bool = False,
) -> int:
    broken: List[str] = []
    unreachable: List[str] = []

    for send, receive in corridors:
        print(f"\n{'=' * 78}")
        print(f"  {send} -> {receive}   amount {amount}")
        print(f"{'=' * 78}")

        selection = select_providers(send, receive, include_benchmark=True)
        relevant = [
            p for p in ALL_PROVIDERS
            if p.meta.supports(send, receive)
        ]
        if not relevant:
            print("  no providers serve this corridor")
            continue

        results = await asyncio.gather(*[probe(p, amount, send, receive) for p in relevant])

        for provider, (status, detail) in sorted(
            zip(relevant, results), key=lambda pair: (pair[0].meta.priority, pair[0].name)
        ):
            tag = {
                "OK": colour("  OK    ", GREEN),
                "BROKEN": colour("BROKEN  ", RED),
                "UNREACHABLE": colour("UNREACH ", BLUE),
                "NO KEY": colour("NO KEY  ", YELLOW),
                "NEEDS JS": colour("NEEDS JS", YELLOW),
                "N/A": colour("  N/A   ", DIM),
            }[status]

            flags = []
            if provider.meta.benchmark_only:
                flags.append("benchmark-only")
            if provider.meta.avoid:
                flags.append("avoid")
            suffix = f" {colour('[' + ', '.join(flags) + ']', DIM)}" if flags else ""

            print(f"  {tag} P{provider.meta.priority} {provider.name:<16}{suffix}")
            print(f"         {colour(detail, DIM)}")

            if status == "BROKEN":
                broken.append(f"{provider.name} ({send}->{receive})")
            elif status == "UNREACHABLE":
                unreachable.append(f"{provider.name} ({send}->{receive})")

        skipped = selection.unavailable
        if skipped:
            print(f"\n  {colour('not called:', DIM)}")
            for name, why in sorted(skipped.items()):
                print(f"    {colour(f'{name}: {why}', DIM)}")

    print(f"\n{'=' * 78}")

    if unreachable:
        print(colour(f"  {len(unreachable)} provider(s) UNREACHABLE:", BLUE))
        for item in unreachable:
            print(f"    - {item}")
        print("\n  These were never contacted, so nothing about them was verified —")
        print("  not the field names, not the selectors, not the numbers. This is a")
        print("  network/egress problem: no edit to sites.py or _parse() will change")
        print("  it. Re-run from a network that can reach the provider hosts.")

    if broken:
        if unreachable:
            print()
        print(colour(f"  {len(broken)} provider(s) BROKEN:", RED))
        for item in broken:
            print(f"    - {item}")
        print("\n  These WERE reached and their answer could not be parsed.")
        print("  Scrapers: fix the selectors in providers/scrapers/sites.py")
        print("  APIs:     fix the field names in the provider's _parse()")
        return 1

    if unreachable and not allow_unreachable:
        print(colour("\n  Nothing broken, but this run verified nothing.", BLUE))
        print("  (Pass --allow-unreachable to exit 0 on a knowingly restricted network.)")
        return 2

    print(colour("  Nothing broken.", GREEN))
    if unreachable:
        print(colour("  (Unreachable providers ignored at your request.)", DIM))
    print("  Now spot-check the numbers against each provider's own website —")
    print("  a parse that succeeds can still be reading the wrong column.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--corridor", action="append", metavar="SEND:RECEIVE",
        help="Corridor to test, e.g. AUD:INR. Repeatable.",
    )
    parser.add_argument("--amount", default="1000", help="Amount in the send currency")
    parser.add_argument(
        "--all-corridors", action="store_true",
        help=f"Test all of: {', '.join(f'{a}:{b}' for a, b in DEFAULT_CORRIDORS)}",
    )
    parser.add_argument(
        "--allow-unreachable", action="store_true",
        help="Exit 0 when the only failures are hosts that could not be "
             "reached. For running on a knowingly restricted network.",
    )
    args = parser.parse_args()

    if args.corridor and args.all_corridors:
        parser.error("--corridor and --all-corridors are mutually exclusive")

    if args.all_corridors:
        corridors = list(DEFAULT_CORRIDORS)
    elif args.corridor:
        corridors = []
        for item in args.corridor:
            if ":" not in item:
                parser.error(f"--corridor expects SEND:RECEIVE, got {item!r}")
            send, receive = item.split(":", 1)
            send, receive = send.strip().upper(), receive.strip().upper()
            if not send or not receive:
                parser.error(f"--corridor expects SEND:RECEIVE, got {item!r}")
            corridors.append((send, receive))
    else:
        corridors = list(DEFAULT_CORRIDORS)

    return asyncio.run(run(corridors, D(args.amount), args.allow_unreachable))


if __name__ == "__main__":
    raise SystemExit(main())
