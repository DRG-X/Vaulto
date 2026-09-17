"""
engine/normalize.py — put every provider on one comparable basis.

The basis
---------
    send_amount = what LEAVES THE SENDER'S ACCOUNT, fee included.

Everything else is derived from that. It is the only basis under which
`receive_amount` means the same thing for every provider, and it is the
question users actually ask: "I have 1000 dollars — who gets my family the
most rupees?"

Putting a quote on that basis is one line of arithmetic:

    principal = send_amount - fee          # the part that gets converted
    receive   = principal * rate

That arithmetic is the same for every provider — the basis is what differs,
not the formula. A fee-on-top provider quoted `1000 * rate` against a budget
of 1000+fee; restating it as `(1000 - fee) * rate` removes the systematic
bias that used to hand those providers an unearned win.

`fee_model` is not consumed here, and deliberately so. It does its work
earlier, in the providers: a DEDUCTED provider is already quoting against the
sender's whole budget, while an ADDED provider has to SOLVE for the principal
(`_quote_fee_inclusive`) because its fee is tiered and re-asking is the only
way to learn the real one. By the time a RawQuote reaches this function both
have landed on the same footing, and the field survives into the response as
provenance — it tells a reader why two providers quoting the same rate and fee
can report different receive amounts.

What decides whether we keep the provider's own `receive_amount` is the
PRINCIPAL, not the model: if the provider converted the same principal we
derived, its published figure was computed on our basis and its own rounding
is authoritative, so we use it verbatim. Otherwise we recompute. That check
is exact for both models — an ADDED provider that solved successfully passes
it, and one whose refinement did not converge correctly fails it.

Cost transparency
-----------------
The headline fee is not the cost. A provider advertising "no fees" typically
takes 2-4% in the exchange rate instead. Total cost is therefore

    total_cost = fee + (mid_market - rate) / mid_market * principal

which is the number Monito ranks on, and the number that makes a "free"
transfer comparable to a 0.5%-fee transfer at a near-perfect rate.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

import delivery
from money import (
    D,
    ZERO,
    HUNDRED,
    currency_exponent,
    is_finite,
    percent_of,
    quantize_money,
    quantize_percent,
    quantize_rate,
    to_float,
    to_str,
)
from providers.quote import RawQuote
from schemas import ProviderQuote


def normalize_quote(
    raw: RawQuote,
    requested_amount: Decimal,
    mid_market_rate: Optional[Decimal] = None,
    meta=None,
) -> ProviderQuote:
    """
    Convert a provider's `RawQuote` into a comparable `ProviderQuote`.

    `requested_amount` is what the sender wants to part with, in full,
    including fees.
    """
    if raw.error is not None or not raw.ok:
        return error_quote(
            provider=raw.provider,
            amount=requested_amount,
            currency_from=raw.currency_from,
            currency_to=raw.currency_to,
            error=raw.error or "Provider returned an incomplete quote",
        )

    send_currency = raw.currency_from
    recv_currency = raw.currency_to

    fee = quantize_money(raw.fee, send_currency)
    rate = quantize_rate(raw.exchange_rate)
    send_amount = quantize_money(requested_amount, send_currency)

    # The part of the sender's money that actually gets converted.
    principal = quantize_money(send_amount - fee, send_currency)

    if principal <= ZERO:
        return error_quote(
            provider=raw.provider,
            amount=requested_amount,
            currency_from=send_currency,
            currency_to=recv_currency,
            error=(
                f"Fee of {fee} {send_currency} meets or exceeds the "
                f"{send_amount} {send_currency} being sent"
            ),
        )

    # Did the provider already convert exactly this principal? If so its own
    # receive figure was computed on our basis, and we must not second-guess
    # its rounding. One minor unit of tolerance absorbs the provider's own
    # rounding of the principal. See the module docstring on why this, and not
    # `fee_model`, is the right test.
    quantum = Decimal(1).scaleb(-currency_exponent(send_currency))
    quoted_on_our_basis = abs(raw.principal - principal) <= quantum

    if quoted_on_our_basis and raw.receive_amount is not None and raw.receive_amount > ZERO:
        receive_amount = quantize_money(raw.receive_amount, recv_currency)
        normalized = False
    else:
        receive_amount = quantize_money(principal * rate, recv_currency)
        normalized = True

    # ── Total cost: visible fee plus the markup buried in the rate ────────
    markup_pct = None
    markup_cost = None
    total_cost = None
    total_cost_pct = None

    if is_finite(mid_market_rate) and mid_market_rate and mid_market_rate > ZERO:
        # Positive markup = the provider's rate is worse than mid-market.
        markup_fraction = (mid_market_rate - rate) / mid_market_rate
        markup_pct = quantize_percent(markup_fraction * HUNDRED)
        markup_cost = quantize_money(principal * markup_fraction, send_currency)
        total_cost = quantize_money(fee + markup_cost, send_currency)
        total_cost_pct = percent_of(total_cost, send_amount)

    transfer_time = delivery.humanize(
        raw.eta_min_minutes, raw.eta_max_minutes, raw.eta_is_business_days
    )
    if raw.pay_out_method:
        transfer_time = f"{transfer_time} ({_label(raw.pay_out_method)})"

    return ProviderQuote(
        provider=raw.provider,
        send_amount=to_float(send_amount),
        fee=to_float(fee),
        exchange_rate=to_float(rate),
        receive_amount=to_float(receive_amount),
        currency_from=send_currency,
        currency_to=recv_currency,
        transfer_time=transfer_time,
        error=None,
        exchange_rate_exact=to_str(rate),
        receive_amount_exact=to_str(receive_amount),
        eta_min_minutes=raw.eta_min_minutes,
        eta_max_minutes=raw.eta_max_minutes,
        eta_is_business_days=raw.eta_is_business_days,
        mid_market_rate=to_float(quantize_rate(mid_market_rate)) if mid_market_rate else None,
        fx_markup_pct=to_float(markup_pct),
        fx_markup_cost=to_float(markup_cost),
        total_cost=to_float(total_cost),
        total_cost_pct=to_float(total_cost_pct),
        category=meta.category.value if meta else None,
        priority=meta.priority if meta else None,
        avoid=bool(meta.avoid) if meta else False,
        fee_model=raw.fee_model.value,
        principal_amount=to_float(principal),
        normalized=normalized,
        pay_in_method=raw.pay_in_method,
        pay_out_method=raw.pay_out_method,
        service_name=raw.service_name,
        is_promotional=raw.is_promotional,
        rate_type=raw.rate_type,
    )


def error_quote(
    provider: str,
    amount: Decimal,
    currency_from: str,
    currency_to: str,
    error: str,
) -> ProviderQuote:
    """A quote that carries the failure, with zeroed — never ranked — numbers."""
    return ProviderQuote(
        provider=provider,
        send_amount=to_float(D(amount)),
        fee=0.0,
        exchange_rate=0.0,
        receive_amount=0.0,
        currency_from=currency_from,
        currency_to=currency_to,
        transfer_time="N/A",
        error=error,
    )


def _label(method: str) -> str:
    """BANK_DEPOSIT -> Bank Deposit."""
    return method.replace("_", " ").title()


def pick_mid_market_rate(raws: list[RawQuote]) -> tuple[Optional[Decimal], Optional[str]]:
    """
    Choose a reference mid-market rate from whatever the providers published.

    Preference order matters. XE's currency-data API is a NEUTRAL source: it
    sells data, not transfers, so it has no stake in how the comparison comes
    out. Wise is next — it quotes at mid-market and publishes the rate — but
    it is also a competitor in the same table, and measuring everyone's markup
    against one competitor's own number is a weaker position than measuring it
    against an independent feed.

    Returns (rate, source) — or (None, None), in which case markup is simply
    not reported. That is deliberate: inventing a reference from the best
    provider's own rate would show that provider a 0% markup and quietly
    flatter it. No reference is better than a self-serving one.
    """
    candidates = [r for r in raws if r.mid_market_rate and r.mid_market_rate > ZERO]
    if not candidates:
        return (None, None)

    for preferred in ("XE", "Wise"):
        for raw in candidates:
            if raw.provider == preferred:
                return (quantize_rate(raw.mid_market_rate), raw.provider)

    best = candidates[0]
    return (quantize_rate(best.mid_market_rate), best.provider)
