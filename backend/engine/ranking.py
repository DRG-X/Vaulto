"""
engine/ranking.py — sort modes and filters.

"Best" is not one thing. Someone paying rent on the 1st needs FASTEST and will
happily lose a few rupees; someone moving savings wants BEST_RATE. Monito
exposes these as explicit user choices rather than picking one for you, and so
do we.

Every ordering below is TOTAL and deterministic: each key ends in the provider
name, so two providers that tie never swap places between two identical
requests. A comparison that reshuffles on refresh reads as broken even when
the numbers are right.
"""

from __future__ import annotations

from typing import Callable, Iterable, List, Optional

import delivery
from schemas import ProviderQuote, SortMode

#: What a day of waiting is worth, as a percentage of the transfer.
#:
#: BEST_VALUE has to trade money against time, which means putting a price on
#: time. Rather than hide that behind opaque weights, we state it: waiting one
#: extra day is treated as costing 0.25% of the amount being sent. On a 1000
#: transfer that is 2.50 a day — so a provider must be at least 2.50 cheaper
#: to justify arriving a day later.
#:
#: Tune this one number to make the mode more impatient or more frugal.
VALUE_DAY_COST_PCT = 0.25

MINUTES_PER_DAY = 1440

#: Charged to a provider that publishes no delivery estimate at all, so an
#: unknown ETA cannot win by saying nothing. Equivalent to ~4 days.
VALUE_UNKNOWN_ETA_PENALTY_PCT = 1.0


# ---------------------------------------------------------------------------
# Sort keys
# ---------------------------------------------------------------------------

def _cheapest_key(q: ProviderQuote):
    # Most received wins. Negated so that ascending sort = best first.
    return (-(q.receive_amount or 0.0), q.provider)


def _fastest_key(q: ProviderQuote):
    # Then cheapest among equally fast options, so "fastest" does not
    # arbitrarily pick the pricier of two same-day providers.
    return delivery.sort_key(q.eta_min_minutes, q.eta_max_minutes) + (
        -(q.receive_amount or 0.0),
        q.provider,
    )


def _lowest_fee_key(q: ProviderQuote):
    # A zero-fee provider with a terrible rate should not beat a 1-dollar-fee
    # provider with a perfect one, so receive amount breaks the tie.
    return (q.fee if q.fee is not None else float("inf"),
            -(q.receive_amount or 0.0),
            q.provider)


def _best_rate_key(q: ProviderQuote):
    # Smallest markup over mid-market. Where no mid-market reference exists,
    # fall back to the raw rate — higher is better for the recipient.
    if q.fx_markup_pct is not None:
        return (0, q.fx_markup_pct, q.provider)
    return (1, -(q.exchange_rate or 0.0), q.provider)


def _best_value_key_factory(quotes: List[ProviderQuote]) -> Callable:
    """
    Score each quote as an EFFECTIVE COST, in percent of the transfer.

        effective_cost% = money_lost_vs_best% + days_waited * VALUE_DAY_COST_PCT

    Both terms are real percentages of the same transfer, so adding them is
    meaningful and the result reads as a number rather than an index: a score
    of 1.3 means "this option effectively costs 1.3% more than the best one,
    once the wait is priced in".

    The obvious alternative — min-max normalizing each axis across the
    candidate set — is broken in a way that matters here. Normalizing throws
    away MAGNITUDE: if three providers are within 5 rupees of each other on an
    83,000 transfer, the cheapest still scores a perfect 0 and the dearest a
    full 1.0, so a rounding-sized price gap outweighs a five-day delay. Scoring
    against the transfer itself keeps small differences small.
    """
    receives = [q.receive_amount for q in quotes if q.receive_amount is not None]
    best_recv = max(receives) if receives else 0.0

    def key(q: ProviderQuote):
        # How much of the transfer this option gives up against the best one.
        if best_recv > 0 and q.receive_amount is not None:
            cost_pct = (best_recv - q.receive_amount) / best_recv * 100.0
        else:
            cost_pct = 0.0

        eta = q.eta_max_minutes if q.eta_max_minutes is not None else q.eta_min_minutes
        if eta is None:
            time_pct = VALUE_UNKNOWN_ETA_PENALTY_PCT
        else:
            time_pct = (eta / MINUTES_PER_DAY) * VALUE_DAY_COST_PCT

        return (cost_pct + time_pct, -(q.receive_amount or 0.0), q.provider)

    return key


def sort_quotes(quotes: List[ProviderQuote], mode: SortMode) -> List[ProviderQuote]:
    """Return a new list ordered best-first under `mode`."""
    if mode == SortMode.FASTEST:
        key = _fastest_key
    elif mode == SortMode.LOWEST_FEE:
        key = _lowest_fee_key
    elif mode == SortMode.BEST_RATE:
        key = _best_rate_key
    elif mode == SortMode.BEST_VALUE:
        key = _best_value_key_factory(quotes)
    else:
        key = _cheapest_key
    return sorted(quotes, key=key)


def winners_by_mode(quotes: List[ProviderQuote]) -> dict:
    """
    Winner under every mode, as {mode_value: provider_name}.

    Computed once so the UI can badge "Cheapest" and "Fastest" on the same
    table without asking the backend again.
    """
    if not quotes:
        return {}
    return {
        mode.value: sort_quotes(quotes, mode)[0].provider
        for mode in SortMode
    }


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def apply_filters(
    quotes: Iterable[ProviderQuote],
    max_eta_minutes: Optional[int] = None,
    pay_in_method: Optional[str] = None,
    pay_out_method: Optional[str] = None,
    include_promo: bool = True,
) -> tuple[List[ProviderQuote], List[str]]:
    """
    Narrow the candidate set.

    Returns (kept, dropped_provider_names). Dropped providers are reported
    separately from failed ones — being filtered out is a user choice, not an
    outage, and conflating the two makes a working provider look broken.

    A quote missing the attribute being filtered on is KEPT. Filters exist to
    exclude what we know does not match, not to punish providers for
    publishing less metadata than their competitors.
    """
    kept: List[ProviderQuote] = []
    dropped: List[str] = []

    for q in quotes:
        if max_eta_minutes is not None:
            # Filter on the WORST case, matching `delivery.sort_key`.
            # "Arrives within an hour" has to mean the money is there within
            # the hour, not that it might be. Filtering on the best case kept
            # a quote labelled "1-20 hours" under a 60-minute limit, because
            # its optimistic end was exactly 60.
            eta = q.eta_max_minutes if q.eta_max_minutes is not None else q.eta_min_minutes
            if eta is not None and eta > max_eta_minutes:
                dropped.append(q.provider)
                continue

        if pay_in_method and q.pay_in_method and q.pay_in_method.upper() != pay_in_method:
            dropped.append(q.provider)
            continue

        if pay_out_method and q.pay_out_method and q.pay_out_method.upper() != pay_out_method:
            dropped.append(q.provider)
            continue

        if not include_promo and q.is_promotional:
            dropped.append(q.provider)
            continue

        kept.append(q)

    return kept, dropped
