"""Sort-mode semantics and cache-key correctness."""

import sys
import types

import pytest

from engine.ranking import apply_filters, sort_quotes, winners_by_mode
from schemas import ProviderQuote, SortMode


def quote(name, receive, fee, eta, markup=None, promo=False, pay_out=None):
    return ProviderQuote(
        provider=name, send_amount=1000.0, fee=fee, exchange_rate=83.0,
        receive_amount=receive, currency_from="USD", currency_to="INR",
        transfer_time="x", eta_min_minutes=eta, eta_max_minutes=eta,
        fx_markup_pct=markup, is_promotional=promo, pay_out_method=pay_out,
    )


@pytest.fixture
def spread():
    return [
        quote("Wise", 82965.87, 5.46, 120, markup=0.00),
        quote("Remitly", 82718.63, 3.99, 7200, markup=0.44),
        quote("WesternUnion", 82550.00, 0.00, 15, markup=1.04),
    ]


class TestSortModes:
    def test_cheapest_maximises_the_recipient(self, spread):
        assert [q.provider for q in sort_quotes(spread, SortMode.CHEAPEST)][0] == "Wise"

    def test_fastest_minimises_arrival(self, spread):
        assert [q.provider for q in sort_quotes(spread, SortMode.FASTEST)][0] == "WesternUnion"

    def test_lowest_fee_ignores_the_rate(self, spread):
        # Deliberately different from "cheapest" — a zero fee can still be
        # the worst deal, which is exactly why both modes exist.
        assert [q.provider for q in sort_quotes(spread, SortMode.LOWEST_FEE)][0] == "WesternUnion"

    def test_best_rate_uses_markup_over_mid_market(self, spread):
        assert [q.provider for q in sort_quotes(spread, SortMode.BEST_RATE)][0] == "Wise"

    def test_best_value_blends_cost_and_speed(self, spread):
        # Wise wins on cost; WU wins on speed. Cost is weighted 0.7, and the
        # cost gap here is wide enough that Wise should still take it.
        assert [q.provider for q in sort_quotes(spread, SortMode.BEST_VALUE)][0] == "Wise"

    def test_best_value_can_favour_speed_when_cost_is_close(self):
        near_tie = [
            quote("Slow", 83000.00, 5.00, 7200),
            quote("Fast", 82995.00, 5.00, 15),
        ]
        assert [q.provider for q in sort_quotes(near_tie, SortMode.BEST_VALUE)][0] == "Fast"

    def test_sorting_never_mutates_the_input(self, spread):
        before = [q.provider for q in spread]
        sort_quotes(spread, SortMode.FASTEST)
        assert [q.provider for q in spread] == before


class TestTieBreaking:
    def test_identical_quotes_order_deterministically(self):
        tied = [quote("Zeta", 100.0, 1.0, 60), quote("Alpha", 100.0, 1.0, 60)]
        for mode in SortMode:
            assert [q.provider for q in sort_quotes(tied, mode)] == ["Alpha", "Zeta"]

    def test_equally_fast_providers_break_on_price(self):
        same_speed = [quote("Pricey", 82000.0, 9.0, 15), quote("Cheap", 83000.0, 1.0, 15)]
        assert [q.provider for q in sort_quotes(same_speed, SortMode.FASTEST)][0] == "Cheap"

    def test_unknown_eta_does_not_win_fastest(self):
        mixed = [quote("Known", 82000.0, 1.0, 1440), quote("Unknown", 83000.0, 1.0, None)]
        assert [q.provider for q in sort_quotes(mixed, SortMode.FASTEST)][0] == "Known"


class TestFilters:
    def test_eta_filter(self, spread):
        kept, dropped = apply_filters(spread, max_eta_minutes=180)
        assert [q.provider for q in kept] == ["Wise", "WesternUnion"]
        assert dropped == ["Remitly"]

    def test_promo_exclusion(self):
        quotes = [quote("Promo", 84000.0, 0.0, 60, promo=True), quote("Base", 83000.0, 1.0, 60)]
        kept, dropped = apply_filters(quotes, include_promo=False)
        assert [q.provider for q in kept] == ["Base"]

    def test_payout_filter_is_case_insensitive(self):
        quotes = [quote("A", 83000.0, 1.0, 60, pay_out="bank_deposit")]
        kept, _ = apply_filters(quotes, pay_out_method="BANK_DEPOSIT")
        assert len(kept) == 1

    def test_missing_metadata_is_kept_not_punished(self):
        # A provider that publishes no ETA should not be silently excluded by
        # a speed filter — we do not know that it fails it.
        quotes = [quote("NoEta", 83000.0, 1.0, None)]
        kept, dropped = apply_filters(quotes, max_eta_minutes=30)
        assert len(kept) == 1
        assert dropped == []

    def test_winners_reflect_the_filtered_set(self, spread):
        kept, _ = apply_filters(spread, max_eta_minutes=180)
        winners = winners_by_mode(kept)
        assert "Remitly" not in winners.values()


class TestCacheKeys:
    @staticmethod
    def _cache():
        # Stub redis so the key builder can be tested without the dependency.
        for name, mod in [
            ("redis", types.ModuleType("redis")),
            ("redis.asyncio", types.ModuleType("redis.asyncio")),
            ("redis.exceptions", types.ModuleType("redis.exceptions")),
        ]:
            sys.modules.setdefault(name, mod)
        sys.modules["redis.asyncio"].Redis = object
        sys.modules["redis.asyncio"].from_url = lambda *a, **k: None
        sys.modules["redis.exceptions"].RedisError = Exception
        import cache
        return cache

    def test_amounts_are_exact_not_bucketed(self):
        cache = self._cache()
        # These used to collapse into one bucket of 500, so a request for 480
        # was answered with a comparison computed for 500.
        assert cache._cache_key("USD", "INR", 480) != cache._cache_key("USD", "INR", 510)

    def test_equivalent_amounts_share_one_key(self):
        cache = self._cache()
        assert cache._cache_key("USD", "INR", 1000) == cache._cache_key("usd", "inr", 1000.0)

    def test_decimal_amounts_survive(self):
        cache = self._cache()
        assert cache._cache_key("USD", "INR", 1000.5).endswith(":1000.5")

    def test_filters_get_their_own_entry(self):
        cache = self._cache()
        # Otherwise a "fastest" request is served a cached "cheapest" ranking.
        assert cache._cache_key("USD", "INR", 1000, "fastest") != \
               cache._cache_key("USD", "INR", 1000, "cheapest")

    def test_key_version_was_bumped_to_retire_bucketed_entries(self):
        cache = self._cache()
        assert cache._cache_key("USD", "INR", 1000).startswith("rates:v2:")
