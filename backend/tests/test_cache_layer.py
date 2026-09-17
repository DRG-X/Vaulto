"""
Caching the fetch layer, not the ranked response.

Filters do not change what we ask providers for, so one upstream fetch has to
serve every filter combination. Caching the ranked output instead would key on
five extra fields and re-fan-out to rate-limited APIs on nearly every request.
"""

import json
from decimal import Decimal

import httpx
import pytest

from engine.comparator import QuotePools, fetch_pools, rank_pools
from schemas import CompareRequest, SortMode
from tests import fixtures


@pytest.fixture
def counting_transport(monkeypatch):
    """Route providers to fixtures and count upstream requests."""
    original = httpx.AsyncClient
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        host = request.url.host
        if "wise" in host:
            return httpx.Response(200, json=fixtures.WISE_COMPARISONS)
        if "remitly" in host:
            return httpx.Response(200, json=fixtures.REMITLY_ESTIMATE)
        return httpx.Response(200, json=fixtures.WESTERN_UNION_CATALOG)

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return calls


def req(**kw):
    base = dict(amount=1000, currency_from="USD", currency_to="INR")
    base.update(kw)
    return CompareRequest(**base)


class TestFetchAndRankAreSeparable:
    @pytest.mark.asyncio
    async def test_one_fetch_serves_every_sort_mode(self, counting_transport):
        pools = await fetch_pools(Decimal("1000"), "USD", "INR")
        upstream_calls = len(counting_transport)

        results = {m: rank_pools(pools, req(sort_by=m)) for m in SortMode}

        assert len(counting_transport) == upstream_calls   # no refetch
        assert len({r.best_provider.provider for r in results.values()}) > 1

    @pytest.mark.asyncio
    async def test_one_fetch_serves_every_filter(self, counting_transport):
        pools = await fetch_pools(Decimal("1000"), "USD", "INR")
        upstream_calls = len(counting_transport)

        rank_pools(pools, req(max_eta_minutes=60))
        rank_pools(pools, req(pay_out_method="BANK_DEPOSIT"))
        rank_pools(pools, req(include_promo=False))

        assert len(counting_transport) == upstream_calls

    @pytest.mark.asyncio
    async def test_ranking_is_pure(self, counting_transport):
        """Re-ranking the same pools must not mutate them."""
        pools = await fetch_pools(Decimal("1000"), "USD", "INR")
        before = {n: len(v) for n, v in pools.pools.items()}

        rank_pools(pools, req(sort_by=SortMode.FASTEST, max_eta_minutes=60))
        rank_pools(pools, req(sort_by=SortMode.CHEAPEST))

        assert {n: len(v) for n, v in pools.pools.items()} == before


class TestSerialization:
    @pytest.mark.asyncio
    async def test_pools_survive_a_json_round_trip(self, counting_transport):
        """What goes into Redis has to come back out identical."""
        pools = await fetch_pools(Decimal("1000"), "USD", "INR")
        restored = QuotePools.from_dict(json.loads(json.dumps(pools.to_dict())))

        assert restored.mid_rate == pools.mid_rate
        assert restored.mid_source == pools.mid_source
        assert set(restored.pools) == set(pools.pools)

        original_ranked = rank_pools(pools, req())
        restored_ranked = rank_pools(restored, req())
        assert [q.provider for q in restored_ranked.quotes] == \
               [q.provider for q in original_ranked.quotes]
        assert restored_ranked.best_provider.receive_amount == \
               original_ranked.best_provider.receive_amount

    @pytest.mark.asyncio
    async def test_exact_values_survive_the_round_trip(self, counting_transport):
        # The whole point of the precision work: a cache hop must not round.
        pools = await fetch_pools(Decimal("1000"), "USD", "INR")
        restored = QuotePools.from_dict(json.loads(json.dumps(pools.to_dict())))

        for name, options in pools.pools.items():
            for before, after in zip(options, restored.pools[name]):
                assert after.receive_amount_exact == before.receive_amount_exact
                assert after.exchange_rate_exact == before.exchange_rate_exact

    @pytest.mark.asyncio
    async def test_errors_survive_the_round_trip(self, monkeypatch):
        original = httpx.AsyncClient

        def handler(request):
            if "wise" in request.url.host:
                return httpx.Response(200, json=fixtures.WISE_COMPARISONS)
            return httpx.Response(503, json={})

        def factory(*a, **k):
            k["transport"] = httpx.MockTransport(handler)
            return original(*a, **k)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        pools = await fetch_pools(Decimal("1000"), "USD", "INR")
        restored = QuotePools.from_dict(json.loads(json.dumps(pools.to_dict())))

        assert len(restored.errors) == len(pools.errors) == 2
        assert all(q.error for q in restored.errors)

    @pytest.mark.asyncio
    async def test_a_missing_mid_market_round_trips_as_none(self, monkeypatch):
        payload = {k: v for k, v in fixtures.WISE_COMPARISONS.items() if k != "midMarketRate"}
        original = httpx.AsyncClient

        def factory(*a, **k):
            k["transport"] = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
            return original(*a, **k)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        pools = await fetch_pools(Decimal("1000"), "USD", "INR")
        restored = QuotePools.from_dict(json.loads(json.dumps(pools.to_dict())))
        assert restored.mid_rate is None
