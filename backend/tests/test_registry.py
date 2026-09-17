"""
Provider selection: corridor rules, credential gating, benchmark exclusion.

With eighteen providers, WHO gets called is as important to correctness as
what they return. A provider asked about a corridor it does not serve reports
a failure that is not a failure, and an unconfigured partner API reported as
"down" hides the ones that are actually down.
"""

import pytest

from providers import ALL_PROVIDERS, select_providers
from providers.meta import ANY, Category, Integration, ProviderMeta


class TestCorridorRules:
    def test_wildcards_match_anything(self):
        meta = ProviderMeta(name="W", category=Category.FINTECH,
                            integration=Integration.PUBLIC_API)
        assert meta.supports("USD", "INR")
        assert meta.supports("AUD", "PHP")

    def test_send_side_wildcard(self):
        meta = ProviderMeta(name="AUBank", category=Category.BANK,
                            integration=Integration.SCRAPE,
                            corridors=(("AUD", ANY),))
        assert meta.supports("AUD", "INR")
        assert meta.supports("AUD", "USD")
        assert not meta.supports("INR", "AUD")

    def test_exact_corridor(self):
        meta = ProviderMeta(name="SBI", category=Category.BANK,
                            integration=Integration.SCRAPE,
                            corridors=(("INR", "AUD"),))
        assert meta.supports("INR", "AUD")
        assert not meta.supports("INR", "USD")
        assert not meta.supports("AUD", "INR")

    def test_matching_is_case_insensitive(self):
        meta = ProviderMeta(name="X", category=Category.BANK,
                            integration=Integration.SCRAPE,
                            corridors=(("INR", "AUD"),))
        assert meta.supports("inr", "aud")


class TestSelection:
    def test_india_side_providers_are_not_asked_about_us_corridors(self):
        """
        The regression this prevents: every India-side bank appearing in
        `failed_providers` on a USD->INR comparison, which makes a healthy
        system look broken and buries the providers that really did fail.
        """
        selection = select_providers("USD", "INR")
        names = {p.name for p in selection.active}

        assert "SBI" not in names
        assert "HDFC Bank" not in names
        assert "BookMyForex" not in names
        assert "SBI" in selection.out_of_corridor

    def test_australian_banks_appear_on_the_aud_corridor(self):
        selection = select_providers("AUD", "INR")
        names = {p.name for p in selection.active}
        assert {"CommBank", "ANZ", "Westpac"} <= names

    def test_india_side_providers_appear_on_the_inr_corridor(self):
        selection = select_providers("INR", "AUD")
        names = {p.name for p in selection.active}
        assert {"SBI", "HDFC Bank", "ICICI Bank", "BookMyForex"} <= names

    def test_wise_covers_both_directions(self):
        # "Wise India" on the provider sheet is this same integration with the
        # direction reversed — it needs no separate provider.
        assert "Wise" in {p.name for p in select_providers("AUD", "INR").active}
        assert "Wise" in {p.name for p in select_providers("INR", "AUD").active}


class TestCredentialGating:
    def test_unconfigured_partner_apis_are_skipped_not_called(self, monkeypatch):
        for var in ("OFX_API_KEY", "INSTAREM_API_KEY", "AIRWALLEX_CLIENT_ID",
                    "AIRWALLEX_API_KEY", "REVOLUT_API_KEY", "XE_ACCOUNT_ID", "XE_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        selection = select_providers("AUD", "INR")
        assert "OFX" not in {p.name for p in selection.active}
        assert "OFX" in selection.needs_credentials
        assert selection.needs_credentials["OFX"] == ["OFX_API_KEY"]

    def test_a_configured_provider_becomes_active(self, monkeypatch):
        monkeypatch.setenv("OFX_API_KEY", "test-key")
        selection = select_providers("AUD", "INR")
        assert "OFX" in {p.name for p in selection.active}

    def test_partially_configured_provider_names_what_is_missing(self, monkeypatch):
        monkeypatch.setenv("AIRWALLEX_CLIENT_ID", "id")
        monkeypatch.delenv("AIRWALLEX_API_KEY", raising=False)
        selection = select_providers("AUD", "INR")
        assert selection.needs_credentials["Airwallex"] == ["AIRWALLEX_API_KEY"]

    def test_blank_credentials_do_not_count_as_configured(self, monkeypatch):
        monkeypatch.setenv("OFX_API_KEY", "   ")
        selection = select_providers("AUD", "INR")
        assert "OFX" in selection.needs_credentials

    def test_reasons_are_actionable(self, monkeypatch):
        monkeypatch.delenv("OFX_API_KEY", raising=False)
        reasons = select_providers("AUD", "INR").unavailable
        assert "OFX_API_KEY" in reasons["OFX"]
        assert "AUD->INR" in reasons["SBI"]


class TestBenchmarkOnly:
    def test_competitor_is_excluded_from_user_facing_results(self):
        """
        The build tracker marks HOP Remit "benchmark only, don't display".
        It must never reach a comparison a user sees.
        """
        selection = select_providers("INR", "AUD")
        assert "HOP Remit" not in {p.name for p in selection.active}

    def test_competitor_is_still_fetchable_for_benchmarking(self):
        selection = select_providers("INR", "AUD", include_benchmark=True)
        assert "HOP Remit" in {p.name for p in selection.benchmark}
        assert "HOP Remit" not in {p.name for p in selection.active}


class TestRegistryIntegrity:
    def test_every_provider_declares_its_own_name(self):
        for provider in ALL_PROVIDERS:
            assert provider.meta.name == provider.name, provider.name

    def test_provider_names_are_unique(self):
        names = [p.name for p in ALL_PROVIDERS]
        assert len(names) == len(set(names))

    def test_all_critical_and_high_providers_are_registered(self):
        """Every Priority 1 and 2 row from the provider master list."""
        registered = {p.name for p in ALL_PROVIDERS}
        expected = {
            # Priority 1 — Critical
            "Wise",          # also covers "Wise India" (direction reverses)
            "Remitly",
            "XE",
            "CommBank",
            "SBI",
            # Priority 2 — High
            "OFX", "InstaReM", "Airwallex", "Revolut", "Western Union",
            "ANZ", "Westpac", "HDFC Bank", "ICICI Bank",
            "BookMyForex", "ExTravelMoney", "HOP Remit",
        }
        assert expected <= registered, expected - registered

    def test_banks_are_flagged_as_avoid(self):
        by_name = {p.name: p for p in ALL_PROVIDERS}
        for name in ("CommBank", "ANZ", "Westpac", "SBI", "HDFC Bank", "ICICI Bank"):
            assert by_name[name].meta.avoid is True, name

    def test_fintechs_are_not_flagged_as_avoid(self):
        by_name = {p.name: p for p in ALL_PROVIDERS}
        for name in ("Wise", "Remitly", "BookMyForex"):
            assert by_name[name].meta.avoid is False, name


class TestBenchmarkIsolationEndToEnd:
    """
    A benchmark-only competitor must not reach user-facing results on the
    SUCCESS path either — that is the case where it would actually leak.
    """

    @pytest.mark.asyncio
    async def test_a_successful_competitor_quote_is_never_ranked(self, monkeypatch):
        import httpx
        from decimal import Decimal
        from engine.comparator import fetch_pools

        PAGE = ("<table><tr><th>Currency</th><th>TT Sell</th></tr>"
                "<tr><td>Australian Dollar (AUD)</td><td>57.5000</td></tr></table>")

        original = httpx.AsyncClient

        def factory(*a, **k):
            k["transport"] = httpx.MockTransport(
                lambda r: httpx.Response(200, text=PAGE)
            )
            return original(*a, **k)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        pools = await fetch_pools(
            Decimal("100000"), "INR", "AUD", include_benchmark=True
        )

        assert "HOP Remit" not in pools.pools
        assert "HOP Remit" not in {q.provider for q in pools.errors}
        # Still captured, for the purpose it was fetched for.
        assert "HOP Remit" in pools.benchmark

    @pytest.mark.asyncio
    async def test_benchmark_quotes_survive_the_cache_round_trip(self, monkeypatch):
        import httpx, json
        from decimal import Decimal
        from engine.comparator import QuotePools, fetch_pools

        PAGE = ("<table><tr><th>Currency</th><th>TT Sell</th></tr>"
                "<tr><td>Australian Dollar (AUD)</td><td>57.5000</td></tr></table>")
        original = httpx.AsyncClient

        def factory(*a, **k):
            k["transport"] = httpx.MockTransport(lambda r: httpx.Response(200, text=PAGE))
            return original(*a, **k)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        pools = await fetch_pools(Decimal("100000"), "INR", "AUD", include_benchmark=True)
        restored = QuotePools.from_dict(json.loads(json.dumps(pools.to_dict())))

        assert set(restored.benchmark) == set(pools.benchmark)
        assert "HOP Remit" not in restored.pools
