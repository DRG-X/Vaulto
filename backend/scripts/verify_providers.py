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

    OK        a plausible quote came back — check the numbers against the
              provider's own website before trusting them
    NO KEY    credentials not configured; nothing to test yet
    N/A       does not serve this corridor or this amount (expected)
    NEEDS JS  the rate lives behind a JavaScript calculator; it needs the
              calculator's JSON endpoint or Playwright, not a selector fix
    BROKEN    reached the provider and could not parse the answer — this is
              the one to fix, and the error says where

A BROKEN scraper is almost always a selector in `sites.py`: open the page,
find the row and column that actually holds the telegraphic-transfer rate, and
update `column_hints` / `currency_names`. That is a data edit, not a code change.

Exit status is non-zero when anything is BROKEN, so this can gate a deploy.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from decimal import Decimal
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from money import D, quantize_money                       # noqa: E402
from providers import ALL_PROVIDERS, select_providers      # noqa: E402
from providers.quote import RawQuote                       # noqa: E402

#: Corridors the provider master list actually targets.
DEFAULT_CORRIDORS = [("AUD", "INR"), ("INR", "AUD")]

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def colour(text: str, code: str) -> str:
    return text if not sys.stdout.isatty() else f"{code}{text}{RESET}"


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
        return ("BROKEN", f"{type(e).__name__}: {e}")

    if raw.error:
        # Reached here means the provider WAS called, so a failure is a real
        # failure. Relabelling every error from a JS-backed provider as
        # "NEEDS JS" would mean a dead URL could never fail the deploy gate.
        return ("BROKEN", raw.error)

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


async def run(corridors: List[Tuple[str, str]], amount: Decimal) -> int:
    broken: List[str] = []

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

        skipped = selection.unavailable
        if skipped:
            print(f"\n  {colour('not called:', DIM)}")
            for name, why in sorted(skipped.items()):
                print(f"    {colour(f'{name}: {why}', DIM)}")

    print(f"\n{'=' * 78}")
    if broken:
        print(colour(f"  {len(broken)} provider(s) BROKEN:", RED))
        for item in broken:
            print(f"    - {item}")
        print("\n  Scrapers: fix the selectors in providers/scrapers/sites.py")
        print("  APIs:     fix the field names in the provider's _parse()")
        return 1

    print(colour("  Nothing broken.", GREEN))
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

    return asyncio.run(run(corridors, D(args.amount)))


if __name__ == "__main__":
    raise SystemExit(main())
