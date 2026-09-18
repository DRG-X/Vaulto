"""
Rail canonicalization.

Providers spell the same rail differently, and `apply_filters` matches
exactly. Without canonicalization a user filtering for "bank deposit" silently
loses every provider that calls it something else — the provider does not
error, it just vanishes into `filtered_out` and the comparison quietly gets
narrower than was asked for.
"""

from decimal import Decimal

import pytest

from engine.normalize import normalize_quote
from engine.ranking import apply_filters
from providers.quote import FeeModel, RawQuote
from providers.rails import canonical_pay_in, canonical_pay_out


class TestCanonicalNames:
    @pytest.mark.parametrize("raw,expected", [
        ("BANK_TRANSFER", "BANK_DEPOSIT"),   # Wise's spelling
        ("BANK_DEPOSIT", "BANK_DEPOSIT"),    # Western Union's
        ("bank deposit", "BANK_DEPOSIT"),
        ("CASH", "CASH_PICKUP"),
        ("mobile money", "MOBILE_WALLET"),
        ("DIRECT_TO_PHONE", "MOBILE_WALLET"),
        ("UPI", "UPI"),
    ])
    def test_pay_out(self, raw, expected):
        assert canonical_pay_out(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("DEBIT_CARD", "DEBIT"),             # Wise's spelling
        ("DEBIT", "DEBIT"),                  # Remitly's
        ("BANK_TRANSFER", "BANK"),
        ("ACH", "BANK"),
        ("CREDIT_CARD", "CREDIT"),
    ])
    def test_pay_in(self, raw, expected):
        assert canonical_pay_in(raw) == expected

    def test_unknown_rails_pass_through_rather_than_being_bucketed(self):
        # A provider inventing a rail should stay filterable by its own name,
        # not be silently folded into a bucket it does not belong in.
        assert canonical_pay_out("CRYPTO_WALLET") == "CRYPTO_WALLET"

    def test_empty_is_none(self):
        assert canonical_pay_out(None) is None
        assert canonical_pay_in("") is None


class TestFiltersMatchAcrossProviders:
    def quote(self, provider, pay_out, pay_in):
        raw = RawQuote(
            provider=provider, currency_from="AUD", currency_to="INR",
            principal=Decimal("1000"), fee=Decimal("5"),
            fee_model=FeeModel.DEDUCTED, exchange_rate=Decimal("54.5"),
            pay_out_method=pay_out, pay_in_method=pay_in,
        )
        return normalize_quote(raw, Decimal("1000"))

    def test_one_filter_matches_every_spelling_of_the_same_rail(self):
        """
        The bug this prevents: filtering "Bank deposit" dropped Wise, because
        Wise calls it BANK_TRANSFER.
        """
        quotes = [
            self.quote("Wise", "BANK_TRANSFER", "BANK_TRANSFER"),
            self.quote("Western Union", "BANK_DEPOSIT", "BANK"),
            self.quote("Remitly", "BANK_DEPOSIT", "DEBIT"),
        ]
        kept, dropped = apply_filters(quotes, pay_out_method="BANK_DEPOSIT")

        assert len(kept) == 3, f"dropped: {dropped}"
        assert dropped == []

    def test_card_funding_matches_across_spellings(self):
        quotes = [
            self.quote("Wise", "BANK_TRANSFER", "DEBIT_CARD"),
            self.quote("Remitly", "BANK_DEPOSIT", "DEBIT"),
            self.quote("OFX", "BANK_DEPOSIT", "BANK"),
        ]
        kept, dropped = apply_filters(quotes, pay_in_method="DEBIT")
        assert {q.provider for q in kept} == {"Wise", "Remitly"}
        assert dropped == ["OFX"]

    def test_a_genuinely_different_rail_is_still_excluded(self):
        quotes = [
            self.quote("Wise", "BANK_TRANSFER", "BANK"),
            self.quote("Western Union", "CASH_PICKUP", "DEBIT"),
        ]
        kept, _ = apply_filters(quotes, pay_out_method="CASH_PICKUP")
        assert [q.provider for q in kept] == ["Western Union"]

    def test_the_label_uses_the_canonical_name(self):
        q = self.quote("Wise", "BANK_TRANSFER", "BANK")
        assert "Bank Deposit" in q.transfer_time
