"""
Comparison engine.

Split into two halves, because they have very different costs:

    fetch_pools()  — talks to every provider concurrently. Expensive, and
                     depends ONLY on the corridor and the amount.
    rank_pools()   — filters, selects and orders. Pure, local, microseconds,
                     and depends on the user's filter choices.

Keeping them apart matters for more than tidiness. Filters do not change what
we ask the providers for, only how their answers are presented, so the
expensive half can be cached once per (corridor, amount) and re-ranked for
free. Fusing them meant every distinct filter combination re-fetched the same
upstream data — and with exact-amount cache keys that is a lot of traffic
into APIs that rate-limit.

Two things here used to corrupt the numbers and are worth calling out:

1. Providers that FAIL do not raise — Remitly and Western Union return a quote
   object carrying an error and zeroed amounts. Those zeros used to flow into
   the ranking, so `savings_vs_worst` measured the winner against a provider
   that never quoted, and `savings_vs_average` averaged real money with zeros.
   Failed providers are now kept out of the maths and reported separately.

2. Quotes were ranked before being re-based onto a common fee model, so the
   ordering itself could be wrong. Normalization happens first, always.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from money import D, quantize_money, to_float, to_str
from schemas import CompareRequest, CompareResponse, ProviderQuote, SortMode
from providers import select_providers
from providers.quote import RawQuote
from engine import normalize as norm
from engine import ranking
from engine import sanity

logger = logging.getLogger(__name__)


@dataclass
class QuotePools:
    """
    Everything the providers told us, normalized but not yet ranked.

    `pools` maps a provider name to ALL of its usable options — every
    pay-in/pay-out combination it offered. Which one the user sees is a
    ranking decision, not a fetching one.
    """

    pools: Dict[str, List[ProviderQuote]] = field(default_factory=dict)
    errors: List[ProviderQuote] = field(default_factory=list)
    mid_rate: Optional[Decimal] = None
    mid_source: Optional[str] = None

    #: Providers never called, and why — corridor or missing credentials.
    unavailable: Dict[str, str] = field(default_factory=dict)

    #: Competitor quotes, fetched for rate tracking only. Deliberately kept
    #: out of `pools` so there is no path by which they reach a user.
    benchmark: Dict[str, List[ProviderQuote]] = field(default_factory=dict)

    # ── Redis round-tripping ──────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "pools": {n: [q.model_dump() for q in qs] for n, qs in self.pools.items()},
            "errors": [q.model_dump() for q in self.errors],
            "mid_rate": to_str(self.mid_rate),
            "mid_source": self.mid_source,
            "unavailable": self.unavailable,
            "benchmark": {n: [q.model_dump() for q in qs] for n, qs in self.benchmark.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QuotePools":
        return cls(
            pools={
                name: [ProviderQuote(**q) for q in quotes]
                for name, quotes in (data.get("pools") or {}).items()
            },
            errors=[ProviderQuote(**q) for q in (data.get("errors") or [])],
            mid_rate=D(data.get("mid_rate"), default=None),
            mid_source=data.get("mid_source"),
            unavailable=dict(data.get("unavailable") or {}),
            benchmark={
                name: [ProviderQuote(**q) for q in quotes]
                for name, quotes in (data.get("benchmark") or {}).items()
            },
        )


async def _safe_fetch(provider, amount: Decimal, currency_from: str, currency_to: str) -> RawQuote:
    """
    Fetch one provider's raw quote, converting any escape into a quote that
    carries its own error.

    A provider blowing up must never take the comparison down with it — the
    whole point of comparing is that partial answers are still useful.
    """
    try:
        raw = await provider.fetch_raw_quote(amount, currency_from, currency_to)
        if raw.ok:
            logger.info(
                "[%s] OK — rate=%s fee=%s principal=%s eta=%s-%s min",
                provider.name, raw.exchange_rate, raw.fee, raw.principal,
                raw.eta_min_minutes, raw.eta_max_minutes,
            )
        else:
            logger.warning("[%s] no usable quote: %s", provider.name, raw.error)
        return raw

    except Exception as e:
        logger.exception("[%s] FAILED", provider.name)
        return RawQuote(
            provider=provider.name,
            currency_from=currency_from,
            currency_to=currency_to,
            error=f"{type(e).__name__}: {e}",
        )


async def fetch_pools(
    amount: Decimal,
    currency_from: str,
    currency_to: str,
    include_benchmark: bool = False,
) -> QuotePools:
    """
    Fetch and normalize every relevant provider's options. The expensive half.

    Depends only on the corridor and the amount — never on filters — so the
    result is safe to cache and re-rank.

    Providers are SELECTED before anything is fetched. With eighteen
    providers, most corridor-specific or credential-gated, calling all of them
    everywhere would fill `failed_providers` with India-side banks on every
    Australian corridor and make a healthy system look broken.
    """
    selection = select_providers(
        currency_from, currency_to,
        include_benchmark=include_benchmark,
        amount=amount,
    )
    meta_by_name = {p.name: p.meta for p in selection.active + selection.benchmark}

    if selection.unavailable:
        logger.info("skipped %d provider(s): %s", len(selection.unavailable), selection.unavailable)

    to_call = selection.active + selection.benchmark
    if not to_call:
        return QuotePools(unavailable=selection.unavailable)

    raws: List[RawQuote] = list(await asyncio.gather(*[
        _safe_fetch(p, amount, currency_from, currency_to) for p in to_call
    ]))

    # One reference rate for the whole comparison, so every provider's markup
    # is measured against the same yardstick.
    mid_rate, mid_source = norm.pick_mid_market_rate(raws)
    if mid_rate:
        logger.info("mid-market reference %s from %s", mid_rate, mid_source)
    else:
        logger.info("no mid-market reference available — markup not reported")

    pools: Dict[str, List[ProviderQuote]] = {}
    errors: List[ProviderQuote] = []

    benchmark: Dict[str, List[ProviderQuote]] = {}

    for raw in raws:
        meta = meta_by_name.get(raw.provider)

        # Reference-only sources (XE) exist to supply the mid-market rate
        # above. They are not products anyone can buy, so they are harvested
        # and then dropped rather than ranked — see ProviderMeta.
        #
        # Keyed on the METADATA, not on the quote: a reference source that
        # FAILED returns an error quote with `reference_only` unset, and
        # checking the quote would put it in `failed_providers` even though it
        # was never going to be ranked.
        if (meta and meta.rate_reference_only) or raw.reference_only:
            continue

        candidates = raw.options or [raw]
        normalized = [
            norm.normalize_quote(option, amount, mid_rate, meta=meta)
            for option in candidates
        ]
        usable = [q for q in normalized if not q.error]

        # Benchmark-only providers are tracked, never shown. That has to hold
        # on SUCCESS as well as on failure — a competitor quoting fine is
        # exactly the case where it would otherwise leak into user-facing
        # results.
        if meta is not None and meta.benchmark_only:
            if usable:
                benchmark[raw.provider] = usable
            continue

        if usable:
            pools[raw.provider] = usable
        else:
            errors.append(normalized[0] if normalized else norm.error_quote(
                raw.provider, amount, currency_from, currency_to,
                raw.error or "No usable quote",
            ))

    # Last line of defence before anything is ranked: drop rates that cannot
    # be right for this corridor. Nine providers read their rate off someone
    # else's HTML and six of those have to invert it, so a silent magnitude
    # error is the most likely way this engine produces a confidently wrong
    # answer. See engine/sanity.py.
    pools, implausible = sanity.filter_implausible(pools, mid_rate)
    for provider, reason in implausible.items():
        errors.append(norm.error_quote(
            provider, amount, currency_from, currency_to, reason,
        ))

    return QuotePools(
        pools=pools,
        errors=errors,
        mid_rate=mid_rate,
        mid_source=mid_source,
        unavailable=selection.unavailable,
        benchmark=benchmark,
    )


def _select_per_provider(
    pools: Dict[str, List[ProviderQuote]],
    request: CompareRequest,
    mode: SortMode,
) -> Tuple[List[ProviderQuote], List[str]]:
    """
    Reduce each provider's options to the single best one under `mode`.

    Filters run WITHIN a provider first, so a provider is only dropped when
    none of its options qualify — a 60-minute limit should pick Western
    Union's minutes option, not discard Western Union.
    """
    chosen: List[ProviderQuote] = []
    dropped: List[str] = []

    for provider, options in pools.items():
        kept, _ = ranking.apply_filters(
            options,
            max_eta_minutes=request.max_eta_minutes,
            pay_in_method=request.pay_in_method,
            pay_out_method=request.pay_out_method,
            include_promo=request.include_promo,
        )
        if not kept:
            dropped.append(provider)
            continue
        chosen.append(ranking.sort_quotes(kept, mode)[0])

    return chosen, dropped


def rank_pools(data: QuotePools, request: CompareRequest) -> CompareResponse:
    """
    Filter, select and order. The cheap half — pure and local.

    Raises ValueError when nothing usable survives.
    """
    quotes, filtered_out = _select_per_provider(data.pools, request, request.sort_by)

    if not quotes and not filtered_out:
        reasons = "; ".join(f"{q.provider}: {q.error}" for q in data.errors)
        if not reasons and data.unavailable:
            reasons = "; ".join(f"{n}: {why}" for n, why in sorted(data.unavailable.items()))
        raise ValueError(
            f"No provider returned a usable quote for "
            f"{request.currency_from}->{request.currency_to}. {reasons or 'unknown'}"
        )

    if not quotes:
        raise ValueError(
            "Every provider was excluded by the filters on this request "
            f"(dropped: {', '.join(sorted(set(filtered_out))) or 'none'}). "
            "Try relaxing max_eta_minutes or the payment-method filter."
        )

    # Savings are always measured on money received, whatever the sort mode —
    # "you save X" is a statement about cash, not about ordering preference.
    savings_vs_worst, savings_vs_average = _savings(quotes, request.currency_to)

    # Each badge is resolved from the FULL option pools under its own mode,
    # not from `quotes`. `quotes` already holds one option per provider chosen
    # under the REQUESTED mode, so reading badges off it would label a
    # provider "Fastest" on the strength of whichever option the user's own
    # sort happened to surface — naming the wrong winner whenever a provider's
    # cheapest option is not also its quickest.
    best_by = {}
    for mode in SortMode:
        per_mode, _ = _select_per_provider(data.pools, request, mode)
        if per_mode:
            best_by[mode.value] = ranking.sort_quotes(per_mode, mode)[0].provider

    quotes = ranking.sort_quotes(quotes, request.sort_by)

    return CompareResponse(
        best_provider=quotes[0],
        quotes=quotes,
        savings_vs_worst=savings_vs_worst,
        savings_vs_average=savings_vs_average,
        request=request,
        failed_providers=[q.provider for q in data.errors],
        best_by=best_by,
        mid_market_rate=to_float(data.mid_rate) if data.mid_rate else None,
        mid_market_rate_exact=to_str(data.mid_rate) if data.mid_rate else None,
        mid_market_source=data.mid_source,
        errors=data.errors,
        filtered_out=sorted(set(filtered_out)),
        unavailable_providers=data.unavailable,
    )


async def compare(request: CompareRequest) -> CompareResponse:
    """Run all providers concurrently and return a ranked comparison."""
    pools = await fetch_pools(D(request.amount), request.currency_from, request.currency_to)
    return rank_pools(pools, request)


def _savings(quotes: List[ProviderQuote], currency_to: str) -> Tuple[float, float]:
    """
    How much the best quote beats the worst, and the average, by.

    Computed in Decimal over successful quotes only. With a single provider
    there is nothing to compare against, so both are zero rather than a
    misleading "you save everything".
    """
    if len(quotes) < 2:
        return (0.0, 0.0)

    receives = [D(q.receive_amount) for q in quotes]
    best = max(receives)
    worst = min(receives)
    average = sum(receives) / Decimal(len(receives))

    return (
        to_float(quantize_money(best - worst, currency_to)),
        to_float(quantize_money(best - average, currency_to)),
    )
