"""
`scripts/verify_providers.py` — the deploy gate's own behaviour.

The script exists to tell three things apart: a provider whose parser is
wrong, a provider that was never reached, and a provider that was never
called. It used to fold the first two together, which turned a blocked
network into a report saying "7 providers BROKEN — fix the selectors in
sites.py" about code that was fine.

These tests pin that distinction, because getting it wrong is silent: the
report still looks authoritative, it just points at the wrong file.
"""

from decimal import Decimal

import httpx
import pytest

from providers.scrapers import SCRAPE_PROVIDERS
from providers.instarem import InstaRemProvider
from scripts import verify_providers as vp


@pytest.fixture(autouse=True)
def clear_reachability_cache():
    """The cache is module-level and would leak a verdict between tests."""
    vp._reachability.clear()
    yield
    vp._reachability.clear()


def transport(monkeypatch, handler):
    """Route every httpx.AsyncClient in this test through `handler`."""
    original = httpx.AsyncClient

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return original(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def scraper(name):
    return next(p for p in SCRAPE_PROVIDERS if p.name == name)


class TestHostReachability:
    @pytest.mark.asyncio
    async def test_an_http_error_response_still_counts_as_reached(self, monkeypatch):
        """
        403 from the provider is not 403 from the proxy.

        The provider answered — we got bytes back. Whatever is wrong is ours
        to fix, so this must NOT be excused as a network problem.
        """
        transport(monkeypatch, lambda request: httpx.Response(403, text="denied"))

        reachable, why = await vp.host_reachable("https://example.com/rates")

        assert reachable is True
        assert why == ""

    @pytest.mark.asyncio
    async def test_a_proxy_denial_counts_as_unreached(self, monkeypatch):
        """An egress policy denying CONNECT never let the request out."""
        def handler(request):
            raise httpx.ProxyError("403 Forbidden")

        transport(monkeypatch, handler)

        reachable, why = await vp.host_reachable("https://example.com/rates")

        assert reachable is False
        assert "ProxyError" in why

    @pytest.mark.asyncio
    async def test_dns_and_refused_connections_count_as_unreached(self, monkeypatch):
        def handler(request):
            raise httpx.ConnectError("[Errno -2] Name or service not known")

        transport(monkeypatch, handler)

        reachable, _ = await vp.host_reachable("https://nope.invalid/")
        assert reachable is False

    @pytest.mark.asyncio
    async def test_a_reset_mid_response_is_the_providers_behaviour(self, monkeypatch):
        """
        We got far enough to be talking to them. That is a real failure, not
        an excuse — otherwise a provider that resets us could never fail CI.
        """
        def handler(request):
            raise httpx.ReadError("connection reset by peer")

        transport(monkeypatch, handler)

        reachable, _ = await vp.host_reachable("https://example.com/")
        assert reachable is True

    @pytest.mark.asyncio
    async def test_each_host_is_probed_once(self, monkeypatch):
        calls = []

        def handler(request):
            calls.append(request.url.host)
            return httpx.Response(200)

        transport(monkeypatch, handler)

        await vp.host_reachable("https://example.com/one")
        await vp.host_reachable("https://example.com/two")

        assert calls == ["example.com"]


class TestCandidateUrls:
    def test_a_scraper_offers_its_configured_page(self):
        provider = scraper("CommBank")
        assert provider.config.url in vp.candidate_urls(provider)

    def test_a_partner_api_offers_its_endpoint(self):
        urls = vp.candidate_urls(InstaRemProvider())
        assert InstaRemProvider.QUOTE_URL in urls

    def test_an_env_override_is_preferred_over_the_documented_url(self, monkeypatch):
        from providers.neobanks import SingXProvider

        monkeypatch.setenv("SINGX_API_URL", "https://sandbox.singx.test/v1/quote")
        SingXProvider.URL_ENV = "SINGX_API_URL"
        try:
            urls = vp.candidate_urls(SingXProvider())
            assert urls[0] == "https://sandbox.singx.test/v1/quote"
        finally:
            SingXProvider.URL_ENV = None

    def test_a_provider_with_no_published_endpoint_does_not_explode(self):
        """TorFX publishes "contact us" rather than a URL."""
        from providers.brokers import TorFXProvider

        assert isinstance(vp.candidate_urls(TorFXProvider()), list)

    def test_every_url_offered_is_absolute(self):
        for provider in vp.ALL_PROVIDERS:
            for url in vp.candidate_urls(provider):
                assert url.startswith(("http://", "https://")), (provider.name, url)


class TestClassifyFailure:
    @pytest.mark.asyncio
    async def test_a_failure_on_a_reachable_host_is_broken(self, monkeypatch):
        transport(monkeypatch, lambda request: httpx.Response(200, text="<html></html>"))

        status, detail = await vp.classify_failure(scraper("CommBank"), "no INR rate found")

        assert status == "BROKEN"
        assert detail == "no INR rate found"

    @pytest.mark.asyncio
    async def test_a_failure_on_an_unreachable_host_is_not_broken(self, monkeypatch):
        def handler(request):
            raise httpx.ProxyError("403 Forbidden")

        transport(monkeypatch, handler)

        status, detail = await vp.classify_failure(
            scraper("CommBank"), "CommBank page unreachable: 403 Forbidden"
        )

        assert status == "UNREACHABLE"
        # The operator has to be able to see it was the network, and still see
        # what the provider itself said.
        assert "not reachable from here" in detail
        assert "CommBank page unreachable" in detail


class TestProbeStatuses:
    @pytest.mark.asyncio
    async def test_a_reachable_page_that_does_not_parse_is_broken(self, monkeypatch):
        """
        The case the whole script is for: we got the page, and our selector
        found nothing in it. This is the one that must fail a deploy.
        """
        transport(
            monkeypatch,
            lambda request: httpx.Response(200, text="<html><body>nothing here</body></html>"),
        )

        status, detail = await vp.probe(
            scraper("CommBank"), Decimal("1000"), "AUD", "INR"
        )

        assert status == "BROKEN"
        assert "no INR rate found" in detail or "layout" in detail

    @pytest.mark.asyncio
    async def test_a_blocked_page_is_unreachable_not_broken(self, monkeypatch):
        def handler(request):
            raise httpx.ProxyError("403 Forbidden")

        transport(monkeypatch, handler)

        status, _ = await vp.probe(scraper("CommBank"), Decimal("1000"), "AUD", "INR")

        assert status == "UNREACHABLE"

    @pytest.mark.asyncio
    async def test_a_wrong_corridor_is_not_a_failure(self):
        status, _ = await vp.probe(scraper("CommBank"), Decimal("1000"), "INR", "AUD")
        assert status == "N/A"

    @pytest.mark.asyncio
    async def test_a_missing_credential_is_not_a_failure(self, monkeypatch):
        monkeypatch.delenv("INSTAREM_API_KEY", raising=False)
        status, detail = await vp.probe(
            InstaRemProvider(), Decimal("1000"), "AUD", "INR"
        )
        assert status == "NO KEY"
        assert "INSTAREM_API_KEY" in detail

    @pytest.mark.asyncio
    async def test_a_js_calculator_is_reported_before_it_is_called(self, monkeypatch):
        js_provider = next(
            (p for p in SCRAPE_PROVIDERS if p.meta.needs_browser), None
        )
        if js_provider is None:
            pytest.skip("no JS-backed scraper configured")

        def handler(request):                      # pragma: no cover
            raise AssertionError("a needs-JS provider must not be fetched")

        transport(monkeypatch, handler)

        send, receive = js_provider.meta.corridors[0]
        status, _ = await vp.probe(js_provider, Decimal("1000"), send, receive)
        assert status == "NEEDS JS"


class TestExitStatus:
    """The gate itself. A green exit must mean something was verified."""

    @pytest.fixture
    def two_scrapers(self, monkeypatch):
        """
        Drive `run()` over a known pair rather than the whole registry.

        An exit-code test that walks all 28 providers changes meaning every
        time one is added, and pays Remitly's real retry backoff to do it.
        """
        pair = [scraper("CommBank"), scraper("Westpac")]
        monkeypatch.setattr(vp, "ALL_PROVIDERS", pair)
        return pair

    @pytest.mark.asyncio
    async def test_a_parse_failure_exits_one(self, monkeypatch, two_scrapers):
        transport(monkeypatch, lambda request: httpx.Response(200, text="<html></html>"))

        code = await vp.run([("AUD", "INR")], Decimal("1000"))
        assert code == 1

    @pytest.mark.asyncio
    async def test_an_unreachable_network_does_not_exit_zero(self, monkeypatch, two_scrapers):
        def handler(request):
            raise httpx.ProxyError("403 Forbidden")

        transport(monkeypatch, handler)

        code = await vp.run([("AUD", "INR")], Decimal("1000"))
        assert code == 2, "a run that verified nothing must not report success"

    @pytest.mark.asyncio
    async def test_unreachable_can_be_accepted_deliberately(self, monkeypatch, two_scrapers):
        def handler(request):
            raise httpx.ProxyError("403 Forbidden")

        transport(monkeypatch, handler)

        code = await vp.run([("AUD", "INR")], Decimal("1000"), allow_unreachable=True)
        assert code == 0

    @pytest.mark.asyncio
    async def test_a_parse_failure_outranks_an_unreachable_host(self, monkeypatch, two_scrapers):
        """
        --allow-unreachable forgives the network, never a broken parser.
        """
        def handler(request):
            if request.url.host == "www.commbank.com.au":
                return httpx.Response(200, text="<html>no rate</html>")
            raise httpx.ProxyError("403 Forbidden")

        transport(monkeypatch, handler)

        code = await vp.run(
            [("AUD", "INR")], Decimal("1000"), allow_unreachable=True
        )
        assert code == 1

    @pytest.mark.asyncio
    async def test_a_clean_run_exits_zero(self, monkeypatch, two_scrapers):
        """The only path that should ever go green."""
        page = (
            "<table><tr><th>Currency</th><th>Telegraphic transfer</th></tr>"
            "<tr><td>Indian Rupee (INR)</td><td>54.2100</td></tr></table>"
        )
        transport(monkeypatch, lambda request: httpx.Response(200, text=page))

        code = await vp.run([("AUD", "INR")], Decimal("1000"))
        assert code == 0
