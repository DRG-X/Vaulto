"""
Fee-model normalization — the correctness fix at the heart of this work.

Providers quote on two incompatible bases. Ranking them without re-basing
compares a sender who spent 1000 against one who spent 1000 + fee.
"""

from decimal import Decimal

import pytest

from engine.normalize import normalize_quote, pick_mid_market_rate
from providers.quote import FeeModel, RawQuote

USD_INR = dict(currency_from="USD", currency_to="INR")


def deducted(rate, fee, amount=Decimal("1000"), receive=None, **kw):
    """A Wise-shaped quote: fee comes out of the amount handed over."""
    return RawQuote(
        provider="Wise", principal=amount - Decimal(fee), fee=Decimal(fee),
        fee_model=FeeModel.DEDUCTED, exchange_rate=Decimal(rate),
        receive_amount=Decimal(receive) if receive else None, **USD_INR, **kw,
    )


def added(rate, fee, amount=Decimal("1000"), receive=None, **kw):
    """A Remitly/WU-shaped quote: fee is charged on top of the principal."""
    return RawQuote(
        provider="Remitly", principal=amount, fee=Decimal(fee),
        fee_model=FeeModel.ADDED, exchange_rate=Decimal(rate),
        receive_amount=Decimal(receive) if receive else None, **USD_INR, **kw,
    )


class TestFeeModelRebasing:
    def test_fee_on_top_provider_is_rebased_onto_the_senders_budget(self):
        # Remitly quoted 1000 * 83.05 = 83,050 for a sender who would actually
        # pay 1003.99. On a 1000 budget only 996.01 gets converted.
        quote = normalize_quote(added("83.05", "3.99"), Decimal("1000"))

        assert quote.principal_amount == 996.01
        assert quote.receive_amount == pytest.approx(82718.63, abs=0.01)
        assert quote.normalized is True
        assert quote.receive_amount < 83050.00

    def test_fee_deducted_provider_keeps_its_own_published_figure(self):
        # Wise already quoted on our basis, so we defer to its own rounding
        # rather than recomputing and risking a one-paisa disagreement.
        quote = normalize_quote(
            deducted("83.4210", "5.46", receive="82965.87"), Decimal("1000")
        )
        assert quote.receive_amount == 82965.87
        assert quote.normalized is False

    def test_the_old_comparison_picked_the_wrong_winner(self):
        """
        The regression this whole change exists to prevent.

        Wise: (1000 - 5.46) * 83.4210 = 82,965.87  <- genuinely better
        Remitly raw: 1000 * 83.05     = 83,050.00  <- looks better, isn't
        Remitly rebased: 996.01 * 83.05 = 82,718.63
        """
        wise = normalize_quote(
            deducted("83.4210", "5.46", receive="82965.87"), Decimal("1000")
        )
        remitly = normalize_quote(added("83.05", "3.99"), Decimal("1000"))

        assert wise.receive_amount > remitly.receive_amount

        naive_remitly = 1000 * 83.05
        assert naive_remitly > wise.receive_amount        # the old bug
        gap = naive_remitly - remitly.receive_amount
        assert gap == pytest.approx(331.37, abs=0.5)      # ~0.4% of the transfer

    def test_both_models_agree_when_the_fee_is_zero(self):
        a = normalize_quote(deducted("83.05", "0"), Decimal("1000"))
        b = normalize_quote(added("83.05", "0"), Decimal("1000"))
        assert a.receive_amount == b.receive_amount


class TestGuards:
    def test_fee_larger_than_the_transfer_is_an_error_not_a_negative_quote(self):
        quote = normalize_quote(added("83.05", "50"), Decimal("25"))
        assert quote.error is not None
        assert quote.receive_amount == 0.0

    def test_broken_raw_quote_becomes_an_error_quote(self):
        quote = normalize_quote(
            RawQuote(provider="X", exchange_rate=Decimal("0"), **USD_INR),
            Decimal("1000"),
        )
        assert quote.error is not None


class TestCurrencyPrecision:
    def test_zero_decimal_target_currency_is_not_given_cents(self):
        raw = RawQuote(
            provider="Wise", currency_from="USD", currency_to="JPY",
            principal=Decimal("1000"), fee=Decimal("0"),
            fee_model=FeeModel.DEDUCTED, exchange_rate=Decimal("157.2345"),
        )
        quote = normalize_quote(raw, Decimal("1000"))
        assert quote.receive_amount == 157235.0       # whole yen
        assert quote.receive_amount_exact == "157235"


class TestExactValuesArePreserved:
    def test_rate_and_receive_survive_as_exact_strings(self):
        quote = normalize_quote(
            deducted("83.42106789", "5.46", receive="82965.87"), Decimal("1000")
        )
        # Trailing zeros are stripped; every significant digit is kept.
        assert Decimal(quote.exchange_rate_exact) == Decimal("83.42106789")
        assert quote.receive_amount_exact == "82965.87"

    def test_exact_string_carries_digits_the_float_field_cannot(self):
        # float(83.421067891234567) collapses; the exact string does not.
        quote = normalize_quote(
            deducted("83.4210678912", "0"), Decimal("1000")
        )
        assert quote.exchange_rate_exact == "83.4210678912"


class TestTotalCost:
    def test_markup_is_measured_against_mid_market(self):
        # 2% worse than mid-market, on a 1000 transfer with no fee.
        raw = deducted("81.7526", "0")          # 83.4210 * 0.98
        quote = normalize_quote(raw, Decimal("1000"), Decimal("83.4210"))

        assert quote.fx_markup_pct == pytest.approx(2.0, abs=0.001)
        assert quote.fx_markup_cost == pytest.approx(20.0, abs=0.01)
        assert quote.total_cost == pytest.approx(20.0, abs=0.01)

    def test_a_zero_fee_provider_can_still_be_the_expensive_one(self):
        """A 'no fees' claim is recovered in the rate; total cost exposes it."""
        free_but_bad_rate = normalize_quote(
            deducted("81.0", "0"), Decimal("1000"), Decimal("83.4210")
        )
        fee_but_good_rate = normalize_quote(
            deducted("83.3", "5.00"), Decimal("1000"), Decimal("83.4210")
        )
        assert free_but_bad_rate.fee == 0.0
        assert free_but_bad_rate.total_cost > fee_but_good_rate.total_cost

    def test_markup_is_omitted_rather_than_guessed_without_a_reference(self):
        quote = normalize_quote(deducted("83.05", "5"), Decimal("1000"), None)
        assert quote.fx_markup_pct is None
        assert quote.total_cost is None


class TestMidMarketSelection:
    def test_prefers_wise_as_the_reference(self):
        raws = [
            RawQuote(provider="Remitly", mid_market_rate=Decimal("83.0"), **USD_INR),
            RawQuote(provider="Wise", mid_market_rate=Decimal("83.4210"), **USD_INR),
        ]
        rate, source = pick_mid_market_rate(raws)
        assert source == "Wise"
        assert rate == Decimal("83.4210000000")

    def test_no_reference_is_better_than_a_self_serving_one(self):
        # Deriving mid-market from the best provider's own rate would show
        # that provider a flattering 0% markup.
        raws = [RawQuote(provider="Remitly", exchange_rate=Decimal("83.0"), **USD_INR)]
        assert pick_mid_market_rate(raws) == (None, None)
