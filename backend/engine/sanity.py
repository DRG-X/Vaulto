"""
engine/sanity.py — reject rates that cannot be right.

Nine of this engine's providers read their rate off someone else's HTML, and
six of those must INVERT it (Indian rate cards quote rupees per Australian
dollar; we need the reverse). Inversion is the single most dangerous thing in
the pipeline: get it backwards on INR->AUD and the rate is out by a factor of
~3,300, the quote looks spectacular, and that provider wins every comparison.
The same applies to a units error, a percentage read as a rate, or a cached
payload replayed onto the wrong corridor.

None of those produce an exception. They produce a number — which is why they
need a check that reasons about MAGNITUDE rather than parsing.

The test is consensus. Providers on one corridor should agree on the rate to
within a few percent; that is what a competitive market means. A quote far
outside that band is not a great deal, it is a bug, and it is dropped with a
reason rather than ranked.

The band is deliberately wide. A real provider is never 25% off the going
rate, so this cannot reject an honest quote — it only catches errors that are
orders of magnitude out.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from money import D, HUNDRED, ZERO
from schemas import ProviderQuote

logger = logging.getLogger(__name__)

#: How far a quote may sit from the reference before it is treated as an
#: error. Genuine spreads between the best and worst provider on a corridor
#: run to a few percent; the worst retail banks reach ~8%. 25% is far outside
#: anything real and far inside an inversion or a units mistake.
MAX_DEVIATION_PCT = Decimal("25")

#: Below this many providers there is no consensus to appeal to, so the check
#: is skipped rather than guessing from too small a sample.
MIN_PROVIDERS_FOR_CONSENSUS = 3


def _median(values: List[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def provider_median(pools: Dict[str, List[ProviderQuote]]) -> Optional[Decimal]:
    """
    Median of each provider's best rate, or None below the consensus minimum.

    Median, not mean: one wildly wrong quote is exactly what this module hunts
    for, and a mean would drift toward it and help it hide.
    """
    per_provider = [
        max(D(q.exchange_rate) for q in options)
        for options in pools.values()
        if options
    ]
    per_provider = [r for r in per_provider if r > ZERO]

    if len(per_provider) < MIN_PROVIDERS_FOR_CONSENSUS:
        return None
    return _median(per_provider)


def reference_rate(
    pools: Dict[str, List[ProviderQuote]],
    mid_rate: Optional[Decimal] = None,
    max_deviation_pct: Decimal = MAX_DEVIATION_PCT,
) -> Optional[Decimal]:
    """
    The rate everything is sanity-checked against.

    Prefers a real mid-market reference — but does not trust it blindly. The
    reference is a SINGLE number from a single source, and if it is wrong
    (a stale cache entry, a payload for the wrong corridor, a provider
    quoting an inverted pair) then trusting it absolutely means rejecting
    every honest provider and keeping none. The failure mode of the safety
    check would be worse than the failure it guards against.

    So when the providers collectively disagree with the reference, the
    providers win. Several independent sources converging is stronger evidence
    than one source asserting.
    """
    median = provider_median(pools)

    if not mid_rate or mid_rate <= ZERO:
        return median

    if median is None:
        # Not enough providers to second-guess the reference with.
        return mid_rate

    drift = deviation_pct(median, mid_rate)
    if drift is not None and drift > max_deviation_pct:
        logger.warning(
            "mid-market reference %s disagrees with the provider consensus %s "
            "by %.0f%% — trusting the consensus. The reference is probably "
            "stale or for a different corridor.",
            mid_rate, median, drift,
        )
        return median

    return mid_rate


def deviation_pct(rate: Decimal, reference: Decimal) -> Optional[Decimal]:
    """How far `rate` sits from `reference`, as a percentage of it."""
    if reference <= ZERO:
        return None
    return abs(rate - reference) / reference * HUNDRED


def filter_implausible(
    pools: Dict[str, List[ProviderQuote]],
    mid_rate: Optional[Decimal] = None,
    max_deviation_pct: Decimal = MAX_DEVIATION_PCT,
) -> Tuple[Dict[str, List[ProviderQuote]], Dict[str, str]]:
    """
    Drop quotes whose rate is impossible for this corridor.

    Returns (kept_pools, rejected) where `rejected` maps a provider name to a
    human-readable reason. A provider losing every option is reported, not
    silently dropped — a scraper reading the wrong column needs fixing, and
    silence is how that goes unnoticed for months.
    """
    reference = reference_rate(pools, mid_rate, max_deviation_pct)
    if reference is None:
        return pools, {}

    kept: Dict[str, List[ProviderQuote]] = {}
    rejected: Dict[str, str] = {}

    for provider, options in pools.items():
        survivors = []
        worst: Optional[Decimal] = None

        for quote in options:
            rate = D(quote.exchange_rate)
            drift = deviation_pct(rate, reference)
            if drift is not None and drift > max_deviation_pct:
                worst = drift if worst is None or drift > worst else worst
                continue
            survivors.append(quote)

        if survivors:
            kept[provider] = survivors
        elif not options:
            # An empty option list is not a bad rate — there is nothing to
            # reject. `reference_rate` already skips these, so treat it the
            # same way rather than formatting a drift that was never computed.
            continue
        else:
            example = D(options[0].exchange_rate)
            drift = f"{worst:.0f}%" if worst is not None else "an unknown amount"
            reason = (
                f"Rate {example} is {drift} away from the {reference} "
                f"reference for this corridor — almost certainly a parsing or "
                f"inversion error, not a real price"
            )
            rejected[provider] = reason
            logger.error("[%s] implausible rate rejected: %s", provider, reason)

    return kept, rejected
