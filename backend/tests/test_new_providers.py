"""
The providers added from the provider master list.

Each is driven through its real `fetch_raw_quote` path with a mock transport.
The payload SHAPES are from published docs, not captured responses — this
session could not reach any provider host. These tests pin our parsing and the
maths built on it; `scripts/verify_providers.py` is what checks the shapes.
"""

from decimal import Decimal

import httpx
import pytest

from providers.airwallex import AirwallexProvider
from providers.instarem import InstaRemProvider
from providers.ofx import OFXProvider
from providers.quote import FeeModel
from providers.revolut import RevolutProvider, is_fx_weekend
from providers.scrapers import SCRAPE_PROVIDERS
from providers.xe import XEProvider


def patch(monkeypatch, payload, status=200, capture=None, text=None):
    original = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=payload)

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def scraper(name):
    return next(p for p in SCRAPE_PROVIDERS if p.name == name)


class TestXE:
    @pytest.mark.asyncio
    async def test_supplies_a_mid_market_reference_not_a_quote(self, monkeypatch):
        """
        XE's currency-data API returns mid-market. Ranking that as XE's own
        price would show a flat 0% markup and win on a rate nobody can buy.
        """
        monkeypatch.setenv("XE_ACCOUNT_ID", "acct")
        monkeypatch.setenv("XE_API_KEY", "key")
        patch(monkeypatch, {"from": "AUD", "amount": 1000,
                            "to": [{"quotecurrency": "INR", "mid": 54.2345, "amount": 54234.5}]})

        raw = await XEProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")

        assert raw.reference_only is True
        assert raw.mid_market_rate == Decimal("54.2345")
        assert XEProvider.meta.rate_reference_only is True

    @pytest.mark.asyncio
    async def test_picks_the_right_quote_currency(self, monkeypatch):
        monkeypatch.setenv("XE_ACCOUNT_ID", "acct")
        monkeypatch.setenv("XE_API_KEY", "key")
        patch(monkeypatch, {"to": [
            {"quotecurrency": "USD", "mid": 0.65},
            {"quotecurrency": "INR", "mid": 54.2345},
        ]})
        raw = await XEProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.mid_market_rate == Decimal("54.2345")

    @pytest.mark.asyncio
    async def test_missing_credentials_are_reported_clearly(self, monkeypatch):
        monkeypatch.delenv("XE_ACCOUNT_ID", raising=False)
        monkeypatch.delenv("XE_API_KEY", raising=False)
        raw = await XEProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert "XE_ACCOUNT_ID" in raw.error


class TestPartnerAPIs:
    @pytest.mark.asyncio
    async def test_ofx_is_fee_free_above_the_threshold(self, monkeypatch):
        monkeypatch.setenv("OFX_API_KEY", "key")
        patch(monkeypatch, {"CustomerRate": 54.10, "InterbankRate": 54.50})

        raw = await OFXProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.fee == Decimal("0")
        assert raw.exchange_rate == Decimal("54.10")
        assert raw.mid_market_rate == Decimal("54.50")

    @pytest.mark.asyncio
    async def test_ofx_charges_below_the_threshold(self, monkeypatch):
        monkeypatch.setenv("OFX_API_KEY", "key")
        patch(monkeypatch, {"CustomerRate": 54.10})
        raw = await OFXProvider().fetch_raw_quote(Decimal("150"), "AUD", "INR")
        assert raw.fee > Decimal("0")

    @pytest.mark.asyncio
    async def test_instarem_sends_the_amount_as_a_string(self, monkeypatch):
        # A float here would reintroduce exactly the precision loss the
        # engine was fixed for, on the way OUT.
        monkeypatch.setenv("INSTAREM_API_KEY", "key")
        captured = []
        patch(monkeypatch, {"data": {"fx_rate": 54.05, "total_fee": 0}}, capture=captured)

        await InstaRemProvider().fetch_raw_quote(Decimal("1000.50"), "AUD", "INR")
        body = captured[0].read().decode()
        # Quoted, so the exact decimal survives the wire. Unquoted it would be
        # a JSON number and re-decoded as a float on the far side.
        assert '"source_amount":"1000.50"' in body.replace(", ", ",")

    @pytest.mark.asyncio
    async def test_rejected_credentials_say_so(self, monkeypatch):
        monkeypatch.setenv("OFX_API_KEY", "wrong")
        patch(monkeypatch, {}, status=403)
        raw = await OFXProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert "credentials" in raw.error.lower()
        assert "OFX_API_KEY" in raw.error

    @pytest.mark.asyncio
    async def test_unexpected_shape_is_contained(self, monkeypatch):
        monkeypatch.setenv("OFX_API_KEY", "key")
        patch(monkeypatch, {"something": "unexpected"})
        raw = await OFXProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.ok is False
        assert raw.error

    @pytest.mark.asyncio
    async def test_airwallex_authenticates_then_quotes(self, monkeypatch):
        monkeypatch.setenv("AIRWALLEX_CLIENT_ID", "id")
        monkeypatch.setenv("AIRWALLEX_API_KEY", "key")
        captured = []

        original = httpx.AsyncClient

        def handler(request):
            captured.append(str(request.url))
            if "authentication" in str(request.url):
                return httpx.Response(200, json={"token": "tok", "expires_in": 1800})
            return httpx.Response(200, json={"items": [{"rate": 54.00, "mid_rate": 54.5}]})

        def factory(*a, **k):
            k["transport"] = httpx.MockTransport(handler)
            return original(*a, **k)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        raw = await AirwallexProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.exchange_rate == Decimal("54.00")
        assert any("authentication" in u for u in captured)

    @pytest.mark.asyncio
    async def test_airwallex_reuses_its_token(self, monkeypatch):
        monkeypatch.setenv("AIRWALLEX_CLIENT_ID", "id")
        monkeypatch.setenv("AIRWALLEX_API_KEY", "key")
        auth_calls = []
        original = httpx.AsyncClient

        def handler(request):
            if "authentication" in str(request.url):
                auth_calls.append(1)
                return httpx.Response(200, json={"token": "tok", "expires_in": 1800})
            return httpx.Response(200, json={"items": [{"rate": 54.00}]})

        def factory(*a, **k):
            k["transport"] = httpx.MockTransport(handler)
            return original(*a, **k)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        provider = AirwallexProvider()
        await provider.fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        await provider.fetch_raw_quote(Decimal("2000"), "AUD", "INR")
        assert len(auth_calls) == 1


class TestRevolutWeekendSurcharge:
    def test_weekend_window_follows_fx_market_hours(self):
        from datetime import datetime, timezone
        # Saturday
        assert is_fx_weekend(datetime(2026, 9, 19, 12, tzinfo=timezone.utc))
        # Friday before close
        assert not is_fx_weekend(datetime(2026, 9, 18, 10, tzinfo=timezone.utc))
        # Friday after close
        assert is_fx_weekend(datetime(2026, 9, 18, 22, tzinfo=timezone.utc))
        # Sunday after reopen
        assert not is_fx_weekend(datetime(2026, 9, 20, 22, tzinfo=timezone.utc))
        # Wednesday
        assert not is_fx_weekend(datetime(2026, 9, 16, 12, tzinfo=timezone.utc))

    @pytest.mark.asyncio
    async def test_weekday_quote_is_passed_through_unmodified(self, monkeypatch):
        monkeypatch.setenv("REVOLUT_API_KEY", "key")
        monkeypatch.setattr("providers.revolut.is_fx_weekend", lambda *a: False)
        patch(monkeypatch, {"rate": 54.50})

        raw = await RevolutProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.exchange_rate == Decimal("54.50")

    @pytest.mark.asyncio
    async def test_never_supplies_the_mid_market_reference(self, monkeypatch):
        """
        Revolut's weekday rate tracks mid-market, but it competes in the same
        comparison. A provider supplying the yardstick its own markup is
        measured against scores itself a flattering 0% — the self-serving
        reference normalize.py rules out. XE is the reference; Wise is the
        fallback.
        """
        monkeypatch.setenv("REVOLUT_API_KEY", "key")
        patch(monkeypatch, {"rate": 54.50})

        for weekend in (False, True):
            monkeypatch.setattr("providers.revolut.is_fx_weekend", lambda *a, w=weekend: w)
            raw = await RevolutProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
            assert raw.mid_market_rate is None

    @pytest.mark.asyncio
    async def test_weekend_quote_is_worse(self, monkeypatch):
        """A Saturday transfer really does cost more — quoting the weekday
        rate would misprice it."""
        monkeypatch.setenv("REVOLUT_API_KEY", "key")
        monkeypatch.setattr("providers.revolut.is_fx_weekend", lambda *a: True)
        patch(monkeypatch, {"rate": 54.50})

        raw = await RevolutProvider().fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.exchange_rate < Decimal("54.50")
        assert "eekend" in (raw.service_name or "")


class TestScrapers:
    AU_PAGE = """<table>
      <tr><th>Currency</th><th>Cash Rate</th><th>TT Sell</th></tr>
      <tr><td>Indian Rupee (INR)</td><td>52.10</td><td>54.2345</td></tr>
    </table>"""

    IN_PAGE = """<table>
      <tr><th>Currency</th><th>TT Sell</th></tr>
      <tr><td>Australian Dollar (AUD)</td><td>57.5000</td></tr>
    </table>"""

    @pytest.mark.asyncio
    async def test_australian_bank_reads_the_tt_rate_not_the_cash_rate(self, monkeypatch):
        # The cash rate is materially worse; picking it misprices the bank.
        patch(monkeypatch, None, text=self.AU_PAGE)
        raw = await scraper("CommBank").fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.exchange_rate == Decimal("54.2345")

    @pytest.mark.asyncio
    async def test_indian_rate_card_is_inverted(self, monkeypatch):
        """
        SBI publishes "AUD 57.50" — one Australian dollar costs 57.50 rupees.
        Our rate is AUD per INR, so it must be 1/57.50. Missing the inversion
        would inflate the quote ~3,300x and rank SBI best on every corridor.
        """
        patch(monkeypatch, None, text=self.IN_PAGE)
        raw = await scraper("SBI").fetch_raw_quote(Decimal("100000"), "INR", "AUD")

        expected = Decimal(1) / Decimal("57.5000")
        assert abs(raw.exchange_rate - expected) < Decimal("0.0000001")
        assert raw.exchange_rate < Decimal("1")

    @pytest.mark.asyncio
    async def test_a_changed_page_fails_loudly_rather_than_guessing(self, monkeypatch):
        # A wrong bank rate is worse than no rate: it would rank a bank best.
        patch(monkeypatch, None, text="<html><body>Our rates have moved</body></html>")
        raw = await scraper("CommBank").fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.ok is False
        assert "layout" in raw.error

    @pytest.mark.asyncio
    async def test_unreachable_page_is_contained(self, monkeypatch):
        patch(monkeypatch, None, status=503, text="down")
        raw = await scraper("ANZ").fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.ok is False
        assert "unreachable" in raw.error

    @pytest.mark.asyncio
    async def test_wrong_corridor_is_refused(self, monkeypatch):
        patch(monkeypatch, None, text=self.AU_PAGE)
        raw = await scraper("CommBank").fetch_raw_quote(Decimal("1000"), "INR", "AUD")
        assert raw.ok is False
        assert "only" in raw.error

    @pytest.mark.asyncio
    async def test_bank_fees_are_charged_on_top(self, monkeypatch):
        patch(monkeypatch, None, text=self.AU_PAGE)
        raw = await scraper("CommBank").fetch_raw_quote(Decimal("1000"), "AUD", "INR")
        assert raw.fee_model is FeeModel.ADDED
        assert raw.fee == Decimal("22")
        assert raw.rate_type == "scraped"


class TestAirwallexConcurrency:
    """
    Providers are module-level singletons and the comparator fans out
    concurrently, so token handling must be safe under parallel calls.
    """

    @pytest.mark.asyncio
    async def test_concurrent_quotes_authenticate_once(self, monkeypatch):
        import asyncio

        monkeypatch.setenv("AIRWALLEX_CLIENT_ID", "id")
        monkeypatch.setenv("AIRWALLEX_API_KEY", "key")

        auth_calls = []
        original = httpx.AsyncClient

        async def slow_auth():
            await asyncio.sleep(0.01)

        def handler(request):
            if "authentication" in str(request.url):
                auth_calls.append(1)
                return httpx.Response(200, json={"token": "tok", "expires_in": 1800})
            assert request.headers["Authorization"] == "Bearer tok"
            return httpx.Response(200, json={"items": [{"rate": 54.00}]})

        def factory(*a, **k):
            k["transport"] = httpx.MockTransport(handler)
            return original(*a, **k)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        provider = AirwallexProvider()
        results = await asyncio.gather(*[
            provider.fetch_raw_quote(Decimal("1000"), "AUD", "INR") for _ in range(5)
        ])

        # One authentication for five concurrent quotes, not five.
        assert len(auth_calls) == 1
        assert all(r.exchange_rate == Decimal("54.00") for r in results)

    @pytest.mark.asyncio
    async def test_failed_auth_does_not_leave_a_stale_token(self, monkeypatch):
        monkeypatch.setenv("AIRWALLEX_CLIENT_ID", "id")
        monkeypatch.setenv("AIRWALLEX_API_KEY", "key")
        original = httpx.AsyncClient

        def factory(*a, **k):
            k["transport"] = httpx.MockTransport(lambda r: httpx.Response(401, json={}))
            return original(*a, **k)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        provider = AirwallexProvider()
        raw = await provider.fetch_raw_quote(Decimal("1000"), "AUD", "INR")

        assert raw.ok is False
        assert "auth failed" in raw.error
        assert provider._token is None
