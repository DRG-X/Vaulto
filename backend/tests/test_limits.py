"""
Transfer limits.

Providers do not move any amount you like, and the limits are not decoration:
brokers offer their best rates precisely BECAUSE they refuse small transfers.
TorFX starts at A$2,000 — without the floor enforced it would win the
comparison for a student sending A$500 with a quote TorFX would decline.
"""

from decimal import Decimal

import pytest

from providers import ALL_PROVIDERS, select_providers
from providers.meta import Category, Integration, ProviderMeta


def meta(**kw):
    base = dict(name="T", category=Category.BROKER, integration=Integration.PARTNER_API)
    base.update(kw)
    return ProviderMeta(**base)


class TestAcceptsAmount:
    def test_below_the_minimum_is_refused_with_a_reason(self):
        m = meta(min_amount=Decimal("2000"), limits_currency="AUD")
        ok, why = m.accepts_amount(Decimal("500"), "AUD")
        assert ok is False
        assert "Minimum" in why and "2000 AUD" in why

    def test_above_the_maximum_is_refused_with_a_reason(self):
        m = meta(max_amount=Decimal("9000"), limits_currency="AUD")
        ok, why = m.accepts_amount(Decimal("12000"), "AUD")
        assert ok is False
        assert "Maximum" in why and "9000 AUD" in why

    def test_the_boundaries_themselves_are_accepted(self):
        m = meta(min_amount=Decimal("2000"), max_amount=Decimal("9000"), limits_currency="AUD")
        assert m.accepts_amount(Decimal("2000"), "AUD")[0] is True
        assert m.accepts_amount(Decimal("9000"), "AUD")[0] is True

    def test_limits_in_another_currency_are_not_applied(self):
        """
        A$2,000 cannot be compared against a rupee amount without a rate we do
        not have at selection time. Not checking is the safe failure — a wrong
        conversion would hide a provider that would happily take the transfer.
        """
        m = meta(min_amount=Decimal("2000"), limits_currency="AUD")
        assert m.accepts_amount(Decimal("500"), "INR") == (True, None)

    def test_no_limits_means_no_restriction(self):
        assert meta().accepts_amount(Decimal("1"), "AUD") == (True, None)

    def test_limits_are_rendered_without_scientific_notation(self):
        m = meta(max_amount=Decimal("1000000"), limits_currency="AUD")
        _, why = m.accepts_amount(Decimal("2000000"), "AUD")
        assert "1000000" in why
        assert "E+" not in why


class TestSelectionRespectsLimits:
    def test_a_broker_is_excluded_below_its_floor(self):
        selection = select_providers("AUD", "INR", amount=Decimal("500"))
        assert "TorFX" not in {p.name for p in selection.active}
        assert "Minimum" in selection.out_of_limits["TorFX"]

    def test_the_same_broker_is_eligible_above_its_floor(self, monkeypatch):
        monkeypatch.setenv("TORFX_API_KEY", "k")
        monkeypatch.setenv("TORFX_API_URL", "https://example.test/rates")
        selection = select_providers("AUD", "INR", amount=Decimal("5000"))
        assert "TorFX" in {p.name for p in selection.active}

    def test_a_capped_provider_is_excluded_above_its_ceiling(self):
        selection = select_providers("AUD", "INR", amount=Decimal("25000"))
        assert "WorldRemit" in selection.out_of_limits      # A$9,000 cap
        assert "Remitly" not in selection.out_of_limits     # A$30,000 cap

    def test_remitly_drops_out_past_its_own_cap(self):
        selection = select_providers("AUD", "INR", amount=Decimal("40000"))
        assert "Remitly" in selection.out_of_limits

    def test_ofx_minimum_matches_its_fee_free_threshold(self):
        below = select_providers("AUD", "INR", amount=Decimal("150"))
        assert "OFX" in below.out_of_limits

    def test_limits_are_reported_as_unavailable_not_failed(self):
        reasons = select_providers("AUD", "INR", amount=Decimal("500")).unavailable
        assert "Minimum" in reasons["TorFX"]

    def test_omitting_the_amount_skips_limit_checks(self):
        # Callers that only want corridor coverage should not have to invent
        # an amount to ask.
        selection = select_providers("AUD", "INR")
        assert selection.out_of_limits == {}

    def test_limits_checked_before_credentials(self, monkeypatch):
        """
        A partner key will not make TorFX move A$500, so the message the user
        sees should name the real blocker.
        """
        monkeypatch.delenv("TORFX_API_KEY", raising=False)
        selection = select_providers("AUD", "INR", amount=Decimal("500"))
        assert "TorFX" in selection.out_of_limits
        assert "TorFX" not in selection.needs_credentials


class TestSheetLimitsWereTranscribed:
    """Spot-check the limits against the provider master list."""

    @pytest.mark.parametrize("name,minimum,maximum", [
        ("TorFX", "2000", None),
        ("Moneycorp", "1000", None),
        ("SingX", "200", "500000"),
        ("WorldRemit", "1", "9000"),
        ("CurrencyFair", "8", "150000"),
        ("Remitly", "10", "30000"),
        ("Western Union", "1", "50000"),
        ("OFX", "200", None),
        ("MoneyGram", "1", "10000"),
        ("Panda Remit", "10", "50000"),
    ])
    def test_limit(self, name, minimum, maximum):
        provider = next(p for p in ALL_PROVIDERS if p.name == name)
        assert provider.meta.min_amount == Decimal(minimum)
        assert provider.meta.max_amount == (Decimal(maximum) if maximum else None)

    def test_lrs_capped_providers_have_no_per_transfer_maximum(self):
        """
        "USD 250,000 LRS" is India's ANNUAL per-person allowance, not a
        per-transaction ceiling — and it is denominated in a third currency.
        Modelling it as a max would wrongly exclude large legitimate transfers.
        """
        for name in ("SBI", "HDFC Bank", "ICICI Bank", "Axis Forex", "Niyo Global"):
            provider = next(p for p in ALL_PROVIDERS if p.name == name)
            assert provider.meta.max_amount is None, name


class TestIndiaOutwardLicensing:
    """
    Sending money out of India needs an RBI AD-II licence under the
    Liberalised Remittance Scheme. The global fintechs and brokers here
    receive rupees; they do not originate them.

    Without this, every AU-side provider would be offered on INR->AUD, fail
    confusingly, and burn a partner API call per comparison on a transfer the
    provider would refuse.
    """

    @pytest.mark.parametrize("name", [
        "Remitly", "Western Union", "OFX", "InstaReM", "Airwallex", "Revolut",
        "CurrencyFair", "WorldRemit", "TorFX", "Moneycorp", "SingX",
    ])
    def test_global_providers_cannot_originate_from_india(self, name):
        provider = next(p for p in ALL_PROVIDERS if p.name == name)
        assert not provider.meta.supports("INR", "AUD"), name
        # Still fine in the other direction.
        assert provider.meta.supports("AUD", "INR"), name

    def test_wise_is_the_exception_because_it_has_an_indian_entity(self):
        """'Wise India' on the provider sheet is this same integration."""
        wise = next(p for p in ALL_PROVIDERS if p.name == "Wise")
        assert wise.meta.supports("INR", "AUD")
        assert wise.meta.supports("AUD", "INR")

    def test_india_side_providers_are_unaffected(self):
        for name in ("SBI", "BookMyForex", "Niyo Global", "Axis Forex"):
            provider = next(p for p in ALL_PROVIDERS if p.name == name)
            assert provider.meta.supports("INR", "AUD"), name

    def test_both_corridors_keep_meaningful_coverage(self):
        au = [p for p in ALL_PROVIDERS if p.meta.supports("AUD", "INR")]
        inr = [p for p in ALL_PROVIDERS if p.meta.supports("INR", "AUD")]
        assert len(au) >= 18
        assert len(inr) >= 10

    def test_excluded_providers_are_not_called_at_all(self):
        from providers import select_providers
        selection = select_providers("INR", "AUD", amount=Decimal("100000"))
        called = {p.name for p in selection.active}
        assert "TorFX" not in called
        assert "WorldRemit" not in called


class TestJavaScriptCalculatorsAreNeverCalled:
    """
    A provider whose rate only exists after JavaScript runs cannot be reached
    by fetching. Calling it anyway costs a 20-second timeout on every
    comparison and parks a permanent entry in `failed_providers` — exactly the
    "healthy system looks broken" failure the registry exists to prevent.
    """

    def test_excluded_from_the_active_set(self):
        selection = select_providers("AUD", "INR", amount=Decimal("1000"))
        active = {p.name for p in selection.active}
        assert "MoneyGram" not in active
        assert "Panda Remit" not in active

    def test_reported_as_unavailable_with_what_they_need(self):
        selection = select_providers("AUD", "INR", amount=Decimal("1000"))
        reason = selection.unavailable["MoneyGram"]
        assert "JavaScript" in reason
        assert "JSON endpoint" in reason or "browser" in reason

    def test_not_reported_as_failures(self):
        selection = select_providers("AUD", "INR", amount=Decimal("1000"))
        assert "MoneyGram" in selection.needs_browser
        assert "MoneyGram" not in selection.needs_credentials
        assert "MoneyGram" not in selection.out_of_corridor

    @pytest.mark.asyncio
    async def test_a_full_comparison_never_fetches_them(self, monkeypatch):
        import httpx
        from engine.comparator import fetch_pools

        fetched = []
        original = httpx.AsyncClient

        def handler(request):
            fetched.append(request.url.host)
            return httpx.Response(503, json={})

        def factory(*a, **k):
            k["transport"] = httpx.MockTransport(handler)
            return original(*a, **k)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        pools = await fetch_pools(Decimal("1000"), "AUD", "INR")

        assert not any("moneygram" in h for h in fetched)
        assert not any("pandaremit" in h for h in fetched)
        assert "MoneyGram" not in {q.provider for q in pools.errors}
        assert "MoneyGram" in pools.unavailable


class TestReferenceSourcesIgnoreTransferLimits:
    def test_a_data_feed_is_never_excluded_on_amount(self, monkeypatch):
        """
        XE sells data, not transfers. Dropping it on an amount would remove
        the mid-market yardstick exactly when the comparison is largest.
        """
        monkeypatch.setenv("XE_ACCOUNT_ID", "a")
        monkeypatch.setenv("XE_API_KEY", "k")

        for amount in ("1", "1000", "5000000"):
            selection = select_providers("AUD", "INR", amount=Decimal(amount))
            assert "XE" in {p.name for p in selection.active}, amount
