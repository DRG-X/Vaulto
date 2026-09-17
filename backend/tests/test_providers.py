"""
Provider parsers, driven through real HTTP plumbing with mocked transports.

These exercise the actual `fetch_raw_quote` path — headers, params, JSON
decoding, option building — rather than calling parse helpers directly, so a
change to the request shape or the decode step is caught.
"""

from decimal import Decimal

import httpx
import pytest

from providers.quote import FeeModel
from providers.remitly import RemitlyProvider
from providers.western_union import WesternUnionProvider
from providers.wise import WiseProvider
from tests import fixtures


def transport(payload, status=200, capture=None):
    """A mock transport that returns `payload` and records requests."""
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


def patch_client(monkeypatch, payload, status=200, capture=None):
    """Force every AsyncClient in the provider modules onto the mock transport."""
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport(payload, status, capture)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


class TestWise:
    @pytest.mark.asyncio
    async def test_selects_the_bank_funded_row_not_the_first_one(self, monkeypatch):
        # The card row is first in the payload. The old code took quotes[0]
        # and compared card-funded pricing against rivals' bank pricing.
        patch_client(monkeypatch, fixtures.WISE_COMPARISONS)
        raw = await WiseProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")

        assert raw.pay_in_method == "BANK_TRANSFER"
        assert raw.fee == Decimal("5.46")
        assert raw.fee_model is FeeModel.DEDUCTED

    @pytest.mark.asyncio
    async def test_keeps_every_option_for_the_engine_to_choose_from(self, monkeypatch):
        patch_client(monkeypatch, fixtures.WISE_COMPARISONS)
        raw = await WiseProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert len(raw.options) == 2
        assert {o.pay_in_method for o in raw.options} == {"BANK_TRANSFER", "DEBIT_CARD"}

    @pytest.mark.asyncio
    async def test_rate_arrives_as_exact_decimal_not_float(self, monkeypatch):
        patch_client(monkeypatch, fixtures.WISE_COMPARISONS)
        raw = await WiseProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert isinstance(raw.exchange_rate, Decimal)
        assert raw.exchange_rate == Decimal("83.4210")

    @pytest.mark.asyncio
    async def test_publishes_the_mid_market_reference(self, monkeypatch):
        patch_client(monkeypatch, fixtures.WISE_COMPARISONS)
        raw = await WiseProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert raw.mid_market_rate == Decimal("83.4210")

    @pytest.mark.asyncio
    async def test_parses_delivery_window(self, monkeypatch):
        patch_client(monkeypatch, fixtures.WISE_COMPARISONS)
        raw = await WiseProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert (raw.eta_min_minutes, raw.eta_max_minutes) == (60, 1200)

    @pytest.mark.asyncio
    async def test_sends_the_amount_as_an_exact_string(self, monkeypatch):
        captured = []
        patch_client(monkeypatch, fixtures.WISE_COMPARISONS, capture=captured)
        await WiseProvider().fetch_raw_quote(Decimal("1000.50"), "USD", "INR")
        assert "sendAmount=1000.50" in str(captured[0].url)

    @pytest.mark.asyncio
    async def test_upstream_failure_yields_an_error_quote_not_an_exception(self, monkeypatch):
        patch_client(monkeypatch, {"error": "boom"}, status=503)
        raw = await WiseProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert raw.error is not None
        assert raw.ok is False


class TestRemitly:
    @pytest.mark.asyncio
    async def test_declares_fee_on_top(self, monkeypatch):
        patch_client(monkeypatch, fixtures.REMITLY_ESTIMATE)
        raw = await RemitlyProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert raw.fee_model is FeeModel.ADDED

    @pytest.mark.asyncio
    async def test_prefers_the_base_rate_over_the_promotional_one(self, monkeypatch):
        # 84.20 is a first-transfer-only rate; ranking on it would quote a
        # returning customer a price they cannot actually get.
        patch_client(monkeypatch, fixtures.REMITLY_ESTIMATE)
        raw = await RemitlyProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert raw.exchange_rate == Decimal("83.05")
        assert raw.is_promotional is False

    @pytest.mark.asyncio
    async def test_string_fields_keep_their_exact_value(self, monkeypatch):
        patch_client(monkeypatch, fixtures.REMITLY_ESTIMATE)
        raw = await RemitlyProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert isinstance(raw.fee, Decimal)
        assert raw.fee == Decimal("3.99")

    @pytest.mark.asyncio
    async def test_solves_for_the_fee_inclusive_principal(self, monkeypatch):
        """
        The refinement loop: ask at 1000, learn the 3.99 fee, re-ask at 996.01.

        The second request is what makes the number exact rather than inferred
        — it gets Remitly's real fee for the principal we actually intend to
        send, which matters wherever a fee tier boundary sits nearby.
        """
        captured = []
        patch_client(monkeypatch, fixtures.REMITLY_ESTIMATE, capture=captured)
        raw = await RemitlyProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")

        assert len(captured) == 2
        assert "amount=1000" in str(captured[0].url)
        assert "amount=996.01" in str(captured[1].url)
        assert raw.principal == Decimal("996.01")
        assert raw.principal + raw.fee == Decimal("1000.00")

    @pytest.mark.asyncio
    async def test_unsupported_corridor_is_reported_not_retried(self, monkeypatch):
        captured = []
        patch_client(monkeypatch, {"error": "bad corridor"}, status=400, capture=captured)
        raw = await RemitlyProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")

        assert "not supported" in raw.error.lower()
        assert len(captured) == 1        # a 400 never succeeds; don't burn retries

    @pytest.mark.asyncio
    async def test_unknown_currency_short_circuits_without_a_request(self, monkeypatch):
        captured = []
        patch_client(monkeypatch, {}, capture=captured)
        raw = await RemitlyProvider().fetch_raw_quote(Decimal("1000"), "USD", "XYZ")
        assert raw.error is not None
        assert captured == []


class TestWesternUnion:
    @pytest.mark.asyncio
    async def test_does_not_pick_the_biggest_receive_amount(self, monkeypatch):
        """
        Cash pickup shows the highest raw receive amount (83,100) but requires
        the recipient to collect it in person. Defaulting to it compared a
        rival's bank-to-bank transfer against a different product.
        """
        patch_client(monkeypatch, fixtures.WESTERN_UNION_CATALOG)
        raw = await WesternUnionProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")

        assert raw.pay_out_method == "BANK_DEPOSIT"
        assert raw.pay_in_method == "BANK"
        assert raw.service_name == "Bank Deposit"

    @pytest.mark.asyncio
    async def test_exposes_every_row_as_an_option(self, monkeypatch):
        patch_client(monkeypatch, fixtures.WESTERN_UNION_CATALOG)
        raw = await WesternUnionProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert len(raw.options) == 3

    @pytest.mark.asyncio
    async def test_speed_indicator_becomes_minutes(self, monkeypatch):
        patch_client(monkeypatch, fixtures.WESTERN_UNION_CATALOG)
        raw = await WesternUnionProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")

        assert (raw.eta_min_minutes, raw.eta_max_minutes) == (2880, 4320)
        assert raw.eta_is_business_days is True

        instant = [o for o in raw.options if o.pay_in_method == "DEBIT"]
        assert all(o.eta_max_minutes == 15 for o in instant)

    @pytest.mark.asyncio
    async def test_declares_fee_on_top(self, monkeypatch):
        patch_client(monkeypatch, fixtures.WESTERN_UNION_CATALOG)
        raw = await WesternUnionProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert raw.fee_model is FeeModel.ADDED

    @pytest.mark.asyncio
    async def test_api_level_error_code_is_surfaced(self, monkeypatch):
        patch_client(monkeypatch, fixtures.WU_UNSUPPORTED_CORRIDOR)
        raw = await WesternUnionProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert "P1008" in raw.error

    @pytest.mark.asyncio
    async def test_zero_fee_row_needs_no_refinement_pass(self, monkeypatch):
        # The preferred row is free, so principal already equals the budget
        # and there is nothing to solve for.
        captured = []
        patch_client(monkeypatch, fixtures.WESTERN_UNION_CATALOG, capture=captured)
        raw = await WesternUnionProvider().fetch_raw_quote(Decimal("1000"), "USD", "INR")
        assert raw.principal == Decimal("1000")
        assert len(captured) == 1
