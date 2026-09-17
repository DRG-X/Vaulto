"""
The Medium and Low priority providers from the master list.

Shapes are from published docs where docs exist; two of these providers
publish no endpoint at all. As everywhere in this package, the payloads pin
our parsing, not the upstream field names — `scripts/verify_providers.py`
checks those.
"""

from decimal import Decimal

import httpx
import pytest

from providers import ALL_PROVIDERS
from providers.brokers import MoneycorpProvider, TorFXProvider
from providers.currencyfair import CurrencyFairProvider
from providers.meta import Category
from providers.neobanks import NiyoGlobalProvider, SingXProvider
from providers.scrapers import SCRAPE_PROVIDERS
from providers.worldremit import WorldRemitProvider


def patch(monkeypatch, payload, status=200, text=None):
    original = httpx.AsyncClient

    def handler(request):
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=payload)

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return original(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def scraper(name):
    return next(p for p in SCRAPE_PROVIDERS if p.name == name)


class TestCurrencyFair:
    @pytest.mark.asyncio
    async def test_parses_a_marketplace_rate(self, monkeypatch):
        monkeypatch.setenv("CURRENCYFAIR_API_KEY", "k")
        patch(monkeypatch, {"rate": 54.60, "fee": 3})
        raw = await CurrencyFairProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.exchange_rate == Decimal("54.60")
        assert raw.fee == Decimal("3")

    @pytest.mark.asyncio
    async def test_a_rate_better_than_mid_market_is_kept(self, monkeypatch):
        """
        P2P matching can legitimately settle better than interbank mid. That
        is a real outcome, not a parsing error, and must not be clamped.
        """
        from engine.normalize import normalize_quote

        monkeypatch.setenv("CURRENCYFAIR_API_KEY", "k")
        patch(monkeypatch, {"rate": 54.80})
        raw = await CurrencyFairProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")

        quote = normalize_quote(raw, Decimal("1000"), Decimal("54.50"))
        assert quote.fx_markup_pct < 0          # better than mid-market
        assert quote.error is None

    def test_is_categorised_as_peer_to_peer(self):
        assert CurrencyFairProvider.meta.category is Category.P2P


class TestWorldRemit:
    @pytest.mark.asyncio
    async def test_upi_payout_is_reported_not_flattened(self, monkeypatch):
        # UPI delivery to India is the reason this provider is interesting,
        # so it must survive into the quote rather than becoming "bank".
        monkeypatch.setenv("WORLDREMIT_API_KEY", "k")
        patch(monkeypatch, {"exchangeRate": 54.20, "fee": 3.99, "payOutMethod": "UPI"})
        raw = await WorldRemitProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.pay_out_method == "UPI"

    @pytest.mark.asyncio
    async def test_payout_aliases_are_normalised(self, monkeypatch):
        monkeypatch.setenv("WORLDREMIT_API_KEY", "k")
        patch(monkeypatch, {"exchangeRate": 54.20, "deliveryMethod": "mobile money"})
        raw = await WorldRemitProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.pay_out_method == "MOBILE_WALLET"


class TestBrokers:
    @pytest.mark.asyncio
    async def test_torfx_says_plainly_that_it_has_no_public_endpoint(self, monkeypatch):
        # Better than a hard-coded guess that 404s and reads as an outage.
        monkeypatch.setenv("TORFX_API_KEY", "k")
        monkeypatch.delenv("TORFX_API_URL", raising=False)
        patch(monkeypatch, {})
        raw = await TorFXProvider().fetch_raw_quote(Decimal("5000"), "AUD", "INR")
        assert raw.ok is False
        assert "TORFX_API_URL" in raw.error

    @pytest.mark.asyncio
    async def test_torfx_uses_the_configured_endpoint(self, monkeypatch):
        monkeypatch.setenv("TORFX_API_KEY", "k")
        monkeypatch.setenv("TORFX_API_URL", "https://partner.example.test/rates")
        patch(monkeypatch, {"customerRate": 54.90})
        raw = await TorFXProvider().fetch_raw_quote(Decimal("5000"), "AUD", "INR")
        assert raw.exchange_rate == Decimal("54.90")

    @pytest.mark.asyncio
    async def test_broker_quotes_carry_no_visible_fee(self, monkeypatch):
        # All of a broker's margin is in the spread — which is exactly what
        # total_cost exists to expose.
        monkeypatch.setenv("MONEYCORP_API_KEY", "k")
        patch(monkeypatch, {"clientRate": 54.70})
        raw = await MoneycorpProvider().fetch_raw_quote(Decimal("5000"), "AUD", "INR")
        assert raw.fee == Decimal("0")
        assert raw.service_name == "Negotiated broker rate"


class TestLimitedAPIs:
    @pytest.mark.asyncio
    async def test_singx_parses_a_quote(self, monkeypatch):
        monkeypatch.setenv("SINGX_API_KEY", "k")
        patch(monkeypatch, {"data": {"rate": 54.35, "fee": 0}})
        raw = await SingXProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.exchange_rate == Decimal("54.35")

    @pytest.mark.asyncio
    async def test_niyo_needs_an_endpoint(self, monkeypatch):
        monkeypatch.setenv("NIYO_API_KEY", "k")
        monkeypatch.delenv("NIYO_API_URL", raising=False)
        patch(monkeypatch, {})
        raw = await NiyoGlobalProvider().fetch_raw_quote(Decimal("100000"), "INR", "AUD")
        assert raw.ok is False

    def test_niyo_is_india_side_only(self):
        assert NiyoGlobalProvider.meta.supports("INR", "AUD")
        assert not NiyoGlobalProvider.meta.supports("AUD", "INR")


class TestNewScrapers:
    AU_PAGE = ("<table><tr><th>Currency</th><th>Cash</th><th>TT Sell</th></tr>"
               "<tr><td>Indian Rupee (INR)</td><td>52.10</td><td>53.9000</td></tr></table>")
    IN_PAGE = ("<table><tr><th>Currency</th><th>TT Sell</th></tr>"
               "<tr><td>Australian Dollar (AUD)</td><td>57.2000</td></tr></table>")

    @pytest.mark.asyncio
    async def test_nab_reads_its_rate_page(self, monkeypatch):
        patch(monkeypatch, None, text=self.AU_PAGE)
        raw = await scraper("NAB").fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.exchange_rate == Decimal("53.9000")
        assert raw.fee == Decimal("18")

    @pytest.mark.asyncio
    async def test_thomas_cook_rate_card_is_inverted(self, monkeypatch):
        patch(monkeypatch, None, text=self.IN_PAGE)
        raw = await scraper("Thomas Cook India").fetch_raw_quote(
            Decimal("100000"), "INR", "AUD"
        )
        assert abs(raw.exchange_rate - Decimal(1) / Decimal("57.2000")) < Decimal("1e-7")

    @pytest.mark.asyncio
    async def test_axis_forex_is_flagged_avoid(self, monkeypatch):
        patch(monkeypatch, None, text=self.IN_PAGE)
        raw = await scraper("Axis Forex").fetch_raw_quote(Decimal("100000"), "INR", "AUD")
        assert raw.ok is True
        assert scraper("Axis Forex").meta.avoid is True

    @pytest.mark.asyncio
    async def test_a_js_calculator_explains_what_it_needs(self, monkeypatch):
        """
        "Needs a browser" and "the selector broke" are different jobs. Sending
        a developer to fix a selector on a page that never had one in its HTML
        wastes an afternoon.
        """
        patch(monkeypatch, None, text="<html><body><div id='app'></div></body></html>")
        raw = await scraper("MoneyGram").fetch_raw_quote(Decimal("1000"), "AUD", "INR")

        assert raw.ok is False
        assert "JavaScript calculator" in raw.error
        assert "JSON endpoint" in raw.error
        assert "selector" not in raw.error

    def test_js_calculators_are_flagged_in_config(self):
        for name in ("MoneyGram", "Panda Remit"):
            assert scraper(name).config.requires_js is True


class TestRosterCompleteness:
    def test_every_provider_from_the_master_list_is_registered(self):
        """
        All 29 rows, minus "Wise India" which is the Wise integration with the
        direction reversed and needs no separate provider.
        """
        registered = {p.name for p in ALL_PROVIDERS}
        expected = {
            # Priority 1 — Critical
            "Wise", "Remitly", "XE", "CommBank", "SBI",
            # Priority 2 — High
            "OFX", "InstaReM", "Airwallex", "Revolut", "Western Union",
            "ANZ", "Westpac", "HDFC Bank", "ICICI Bank",
            "BookMyForex", "ExTravelMoney", "HOP Remit",
            # Priority 3 — Medium
            "CurrencyFair", "TorFX", "NAB", "MoneyGram", "Thomas Cook India",
            "Niyo Global", "Axis Forex", "WorldRemit", "Panda Remit",
            # Priority 4 — Low
            "SingX", "Moneycorp",
        }
        assert expected <= registered, expected - registered
        assert len(ALL_PROVIDERS) == 28

    def test_priorities_match_the_sheet(self):
        by_name = {p.name: p.meta.priority for p in ALL_PROVIDERS}
        assert by_name["CurrencyFair"] == 3
        assert by_name["NAB"] == 3
        assert by_name["SingX"] == 4
        assert by_name["Moneycorp"] == 4

    def test_both_corridors_have_real_coverage(self):
        from providers import select_providers

        au = select_providers("AUD", "INR", amount=Decimal("1000"))

        # Counting everything that is corridor-eligible, configured or not.
        # The India side is smaller by design: only providers with an RBI
        # AD-II licence can originate rupees (see TestIndiaOutwardLicensing).
        au_eligible = [p for p in ALL_PROVIDERS if p.meta.supports("AUD", "INR")]
        inr_eligible = [p for p in ALL_PROVIDERS if p.meta.supports("INR", "AUD")]
        assert len(au_eligible) >= 18
        assert len(inr_eligible) >= 10

        # And with no credentials at all, the public providers still work.
        assert {"Wise", "Remitly", "Western Union"} <= {p.name for p in au.active}


class TestBrokerPayloadShapes:
    """
    Brokers publish no schema, so `_parse` accepts several spellings. The
    container paths and the leaf field names must not overlap, or a flat
    response makes the payload the number itself and every lookup misses.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [
        {"rate": 54.90},
        {"customerRate": 54.90},
        {"quote": {"clientRate": 54.90}},
        {"data": {"dealRate": 54.90}},
    ])
    async def test_flat_and_nested_shapes_both_parse(self, monkeypatch, payload):
        monkeypatch.setenv("MONEYCORP_API_KEY", "k")
        patch(monkeypatch, payload)
        raw = await MoneycorpProvider().fetch_raw_quote(Decimal("5000"), "AUD", "INR")
        assert raw.ok is True, payload
        assert raw.exchange_rate == Decimal("54.90"), payload
