"""
Rejecting rates that cannot be right.

The scrapers are the reason this exists. Six of them invert an Indian rate
card, and an inversion done backwards produces a number ~3,300x too good that
wins every comparison without raising anything.
"""

from decimal import Decimal

import pytest

from engine.sanity import (
    deviation_pct,
    filter_implausible,
    reference_rate,
)
from schemas import ProviderQuote


def q(name, rate):
    return ProviderQuote(
        provider=name, send_amount=1000, fee=0, exchange_rate=rate,
        receive_amount=0, currency_from="INR", currency_to="AUD",
        transfer_time="x",
    )


def pools(**kwargs):
    return {name: [q(name, rate)] for name, rate in kwargs.items()}


class TestReference:
    def test_prefers_a_real_mid_market_rate(self):
        assert reference_rate(pools(A=0.0174, B=0.0175), Decimal("0.0176")) == Decimal("0.0176")

    def test_falls_back_to_the_median(self):
        ref = reference_rate(pools(A=0.0174, B=0.0175, C=0.0176))
        assert ref == Decimal("0.0175")

    def test_median_not_mean_so_one_bad_quote_cannot_drag_it(self):
        # A mean here would be ~14, and the broken quote would look normal.
        ref = reference_rate(pools(A=0.0174, B=0.0175, C=0.0176, Broken=57.5))
        assert ref < Decimal("1")

    def test_too_few_providers_means_no_consensus(self):
        assert reference_rate(pools(A=0.0174, B=0.0175)) is None

    def test_no_reference_skips_the_check_entirely(self):
        data = pools(A=0.0174, B=99999)
        kept, rejected = filter_implausible(data)
        assert rejected == {}
        assert set(kept) == {"A", "B"}


class TestRejection:
    def test_an_uninverted_indian_rate_card_is_caught(self):
        """SBI publishes 57.50 INR per AUD; forgetting to invert gives 57.50
        as the AUD-per-INR rate, which would rank it best by a mile."""
        data = pools(BookMyForex=0.017889, ICICI=0.0175, SBI=0.017391, Broken=57.50)
        kept, rejected = filter_implausible(data)

        assert "Broken" in rejected
        assert "inversion" in rejected["Broken"]
        assert set(kept) == {"BookMyForex", "ICICI", "SBI"}

    def test_normal_competitive_spread_is_untouched(self):
        # Best-to-worst on a real corridor is a few percent, nowhere near 25%.
        data = pools(Wise=83.42, Remitly=83.05, WU=82.55, Bank=77.00)
        kept, rejected = filter_implausible(data)
        assert rejected == {}
        assert len(kept) == 4

    def test_the_threshold_is_wide_enough_for_a_terrible_bank(self):
        # A bank 8% off mid-market is expensive, not broken.
        data = pools(A=83.42, B=83.00, C=82.50, Bank=76.75)
        kept, rejected = filter_implausible(data, Decimal("83.42"))
        assert "Bank" in kept

    def test_a_provider_keeps_its_plausible_options(self):
        data = {
            "Multi": [q("Multi", 0.0175), q("Multi", 57.50)],
            "A": [q("A", 0.0174)],
            "B": [q("B", 0.0176)],
        }
        kept, rejected = filter_implausible(data)
        assert len(kept["Multi"]) == 1
        assert kept["Multi"][0].exchange_rate == 0.0175
        assert "Multi" not in rejected

    def test_rejection_reason_names_the_numbers(self):
        data = pools(A=0.0174, B=0.0175, C=0.0176, Broken=57.5)
        _, rejected = filter_implausible(data)
        assert "57.5" in rejected["Broken"]

    def test_deviation_maths(self):
        assert deviation_pct(Decimal("110"), Decimal("100")) == Decimal("10")
        assert deviation_pct(Decimal("90"), Decimal("100")) == Decimal("10")
        assert deviation_pct(Decimal("100"), Decimal("0")) is None


class TestIntegrationWithTheEngine:
    @pytest.mark.asyncio
    async def test_a_broken_scraper_is_reported_not_ranked(self, monkeypatch):
        """End to end: an inverted scraper must reach `errors`, never `quotes`."""
        import httpx
        from engine.comparator import compare
        from schemas import CompareRequest

        # Indian rate cards, but one page serves an un-inverted AUD-per-INR
        # figure that our config would take at face value.
        GOOD = ("<table><tr><th>Currency</th><th>TT Sell</th></tr>"
                "<tr><td>Australian Dollar (AUD)</td><td>57.5000</td></tr></table>")
        BROKEN = ("<table><tr><th>Currency</th><th>TT Sell</th></tr>"
                  "<tr><td>Australian Dollar (AUD)</td><td>0.0174</td></tr></table>")

        original = httpx.AsyncClient

        def handler(request):
            host = request.url.host
            if "bookmyforex" in host:
                return httpx.Response(200, text=BROKEN)   # already inverted upstream
            if any(h in host for h in ("sbi", "hdfc", "icici", "extravelmoney", "moneyhop")):
                return httpx.Response(200, text=GOOD)
            return httpx.Response(503, json={})

        def factory(*a, **k):
            k["transport"] = httpx.MockTransport(handler)
            return original(*a, **k)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        result = await compare(
            CompareRequest(amount=100000, currency_from="INR", currency_to="AUD")
        )

        quoted = {q.provider for q in result.quotes}
        assert "BookMyForex" not in quoted
        assert "BookMyForex" in result.failed_providers

        # And every surviving quote is in the right order of magnitude.
        for quote in result.quotes:
            assert quote.exchange_rate < 1


class TestTheGuardCannotBackfire:
    """
    A safety check that rejects everything is worse than no check.

    The reference is one number from one source. When it is wrong — a stale
    cache entry, a payload for another corridor — trusting it absolutely would
    throw away every honest provider and keep none.
    """

    def test_a_wrong_reference_loses_to_provider_consensus(self):
        # Four providers agree on ~0.0175; the "reference" is a whole
        # corridor out. The providers should survive, not be wiped.
        data = pools(A=0.0174, B=0.0175, C=0.0176, D=0.0175)
        kept, rejected = filter_implausible(data, Decimal("83.42"))

        assert rejected == {}
        assert len(kept) == 4

    def test_a_good_reference_still_wins_over_a_bad_provider(self):
        data = pools(A=0.0174, B=0.0175, C=0.0176, Broken=57.5)
        kept, rejected = filter_implausible(data, Decimal("0.0176"))

        assert "Broken" in rejected
        assert set(kept) == {"A", "B", "C"}

    def test_reference_is_trusted_when_there_is_no_consensus_to_check_it(self):
        # Two providers is below the consensus minimum, so the reference
        # stands and the outlier is still caught.
        data = pools(A=0.0175, Broken=57.5)
        kept, rejected = filter_implausible(data, Decimal("0.0176"))
        assert "Broken" in rejected
        assert "A" in kept

    def test_a_real_bank_spread_survives_a_real_reference(self):
        # Wise at mid-market, a bank ~5% worse: expensive, not broken.
        data = pools(Wise=83.42, Remitly=83.05, WU=82.55, CommBank=79.25)
        kept, rejected = filter_implausible(data, Decimal("83.4210"))
        assert rejected == {}
        assert len(kept) == 4
