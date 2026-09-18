"""
providers/rails.py — canonical names for payment rails.

Providers spell the same rail differently. Wise says `BANK_TRANSFER` where
Western Union says `BANK_DEPOSIT`; Wise says `DEBIT_CARD` where Remitly says
`DEBIT`. Left alone, those are just strings — and `ranking.apply_filters`
matches them exactly, so a user filtering for "bank deposit" silently loses
every provider that happens to call it something else.

That failure is invisible: the provider does not error, it just vanishes into
`filtered_out`, and the comparison quietly gets narrower than the user asked
for. So rails are canonicalized once, at the point a quote is normalized,
rather than being compared as raw provider vocabulary.

The canonical names are the ones the API documents and the filter UI offers.
Anything unrecognised is passed through unchanged (upper-cased) — a provider
inventing a new rail should still be filterable by its own name, not silently
folded into a bucket it does not belong in.
"""

from __future__ import annotations

from typing import Optional

#: How money leaves the sender.
PAY_IN_ALIASES = {
    "BANK": "BANK",
    "BANK_TRANSFER": "BANK",
    "BANK_DEBIT": "BANK",
    "ACH": "BANK",
    "DIRECT_DEBIT": "BANK",
    "PAYTO": "BANK",
    "SWIFT": "BANK",
    "DEBIT": "DEBIT",
    "DEBIT_CARD": "DEBIT",
    "CREDIT": "CREDIT",
    "CREDIT_CARD": "CREDIT",
    "APPLE_PAY": "APPLE_PAY",
    "GOOGLE_PAY": "GOOGLE_PAY",
}

#: How money reaches the recipient.
PAY_OUT_ALIASES = {
    "BANK_DEPOSIT": "BANK_DEPOSIT",
    "BANK_TRANSFER": "BANK_DEPOSIT",
    "BANK": "BANK_DEPOSIT",
    "BANKDEPOSIT": "BANK_DEPOSIT",
    "UPI": "UPI",
    "CASH_PICKUP": "CASH_PICKUP",
    "CASH": "CASH_PICKUP",
    "MOBILE_WALLET": "MOBILE_WALLET",
    "MOBILE": "MOBILE_WALLET",
    "MOBILE_MONEY": "MOBILE_WALLET",
    "DIRECT_TO_PHONE": "MOBILE_WALLET",
    "PUSH_TO_CARD": "PUSH_TO_CARD",
    "HOME_DELIVERY": "HOME_DELIVERY",
}


def _canon(value, table) -> Optional[str]:
    if not value:
        return None
    key = str(value).strip().upper().replace(" ", "_").replace("-", "_")
    if not key:
        return None
    return table.get(key, key)


def canonical_pay_in(value) -> Optional[str]:
    """Canonical funding rail, or None."""
    return _canon(value, PAY_IN_ALIASES)


def canonical_pay_out(value) -> Optional[str]:
    """Canonical delivery rail, or None."""
    return _canon(value, PAY_OUT_ALIASES)
