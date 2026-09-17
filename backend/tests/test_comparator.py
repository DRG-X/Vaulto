"""
End-to-end comparison: three providers, one ranked answer.

Each provider is pinned to its own recorded payload so the whole pipeline
runs — parse, re-base, markup, filter, rank.
"""

import httpx
import pytest

from engine.comparator import compare
from schemas import CompareRequest, SortMode
from tests import fixtures


@pytest.fixture
def live_providers(monkeypatch):
    """Route each provider's host to its recorded payload."""
    original = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "wise" in host:
            return httpx.Response(200, json=fixtures.WISE_COMPARISONS)
        if "remitly" in host:
            return httpx.Response(200, json=fixtures.REMITLY_ESTIMATE)
        if "westernunion" in host:
            return httpx.Response(200, json=fixtures.WESTERN_UNION_CATALOG)
        return httpx.Response(404, json={})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def req(**kw):
    base = dict(amount=1000, currency_from="USD", currency_to="INR")
    base.update(kw)
    return CompareRequest(**base)


class TestRanking:
    @pytest.mark.asyncio
    async def test_all_three_providers_quote(self, live_providers):
        result = await compare(req())
        assert {q.provider for q in result.quotes} == {"Wise", "Remitly", "Western Union"}
        assert result.failed_providers == []

    @pytest.mark.asyncio
    async def test_every_quote_is_on_the_same_basis(self, live_providers):
        """
        The invariant that makes the comparison mean anything: each provider's
        principal plus its fee equals the sender's 1000, so `receive_amount`
        answers one question for all of them.
        """
        result = await compare(req())
        for q in result.quotes:
            assert q.send_amount == 1000.00
            assert round(q.principal_amount + q.fee, 2) == 1000.00

    @pytest.mark.asyncio
    async def test_cheapest_is_the_default_and_maximises_the_recipient(self, live_providers):
        result = await compare(req())
        receives = [q.receive_amount for q in result.quotes]
        assert receives == sorted(receives, reverse=True)
        assert result.best_provider.receive_amount == max(receives)

    @pytest.mark.asyncio
    async def test_fastest_picks_a_different_winner(self, live_providers):
        """Speed is a genuinely different question from price."""
        cheapest = await compare(req(sort_by=SortMode.CHEAPEST))
        fastest = await compare(req(sort_by=SortMode.FASTEST))

        assert fastest.best_provider.eta_max_minutes <= min(
            q.eta_max_minutes for q in cheapest.quotes if q.eta_max_minutes is not None
        )

    @pytest.mark.asyncio
    async def test_fastest_selects_the_quick_option_within_a_provider(self, live_providers):
        # Western Union's bank row takes 2-3 days; its debit row lands in
        # minutes. Asking for speed should switch rows, not drop the provider.
        result = await compare(req(sort_by=SortMode.FASTEST))
        wu = next(q for q in result.quotes if q.provider == "Western Union")
        assert wu.pay_in_method == "DEBIT"
        assert wu.eta_max_minutes == 15

    @pytest.mark.asyncio
    async def test_badges_are_computed_for_every_mode(self, live_providers):
        result = await compare(req())
        assert set(result.best_by) == {
            "cheapest", "fastest", "lowest_fee", "best_rate", "best_value"
        }

    @pytest.mark.asyncio
    async def test_ordering_is_stable_across_identical_requests(self, live_providers):
        a = await compare(req())
        b = await compare(req())
        assert [q.provider for q in a.quotes] == [q.provider for q in b.quotes]


class TestFilters:
    @pytest.mark.asyncio
    async def test_speed_filter_keeps_providers_that_have_a_fast_option(self, live_providers):
        result = await compare(req(max_eta_minutes=60))
        # The GUARANTEED arrival must fit the limit, not just the optimistic
        # end of the range.
        assert all(q.eta_max_minutes <= 60 for q in result.quotes)
        assert "Western Union" in {q.provider for q in result.quotes}

    @pytest.mark.asyncio
    async def test_speed_filter_rejects_a_quote_whose_worst_case_overruns(self, live_providers):
        """Wise's bank row is "1-20 hours"; a 60-minute limit must not keep it."""
        result = await compare(req(max_eta_minutes=60))
        wise = next(q for q in result.quotes if q.provider == "Wise")
        assert wise.eta_max_minutes == 30          # the card row, not the bank row
        assert wise.pay_in_method == "DEBIT_CARD"

    @pytest.mark.asyncio
    async def test_payout_filter_narrows_to_one_rail(self, live_providers):
        result = await compare(req(pay_out_method="CASH_PICKUP"))
        assert all(
            q.pay_out_method == "CASH_PICKUP"
            for q in result.quotes if q.pay_out_method
        )

    @pytest.mark.asyncio
    async def test_filtering_everything_out_says_so(self, live_providers):
        with pytest.raises(ValueError, match="filters"):
            await compare(req(max_eta_minutes=1, pay_out_method="HOME_DELIVERY"))


class TestSavingsMaths:
    @pytest.mark.asyncio
    async def test_savings_are_consistent_with_the_quotes(self, live_providers):
        result = await compare(req())
        receives = [q.receive_amount for q in result.quotes]

        assert result.savings_vs_worst == pytest.approx(max(receives) - min(receives), abs=0.01)
        assert result.savings_vs_average == pytest.approx(
            max(receives) - sum(receives) / len(receives), abs=0.01
        )

    @pytest.mark.asyncio
    async def test_a_failed_provider_never_enters_the_savings_maths(self, monkeypatch):
        """
        The old bug: a failed provider returned a quote with receive_amount 0,
        which was ranked last and averaged in. `savings_vs_worst` then measured
        the winner against zero — a number in the tens of thousands.
        """
        original = httpx.AsyncClient

        def handler(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            if "wise" in host:
                return httpx.Response(200, json=fixtures.WISE_COMPARISONS)
            if "remitly" in host:
                return httpx.Response(200, json=fixtures.REMITLY_ESTIMATE)
            return httpx.Response(503, json={})       # WU is down

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        result = await compare(req())

        assert "Western Union" in result.failed_providers
        assert all(q.receive_amount > 0 for q in result.quotes)
        assert result.savings_vs_worst < 1000        # not ~83,000
        assert len(result.errors) == 1
        assert result.errors[0].error

    @pytest.mark.asyncio
    async def test_a_single_surviving_provider_claims_no_savings(self, monkeypatch):
        original = httpx.AsyncClient

        def handler(request: httpx.Request) -> httpx.Response:
            if "wise" in request.url.host:
                return httpx.Response(200, json=fixtures.WISE_COMPARISONS)
            return httpx.Response(503, json={})

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        result = await compare(req())
        assert len(result.quotes) == 1
        assert result.savings_vs_worst == 0.0
        assert result.savings_vs_average == 0.0


class TestMarkup:
    @pytest.mark.asyncio
    async def test_markup_is_reported_against_wises_mid_market_rate(self, live_providers):
        result = await compare(req())
        assert result.mid_market_source == "Wise"
        assert result.mid_market_rate == pytest.approx(83.4210)

        # Wise quotes AT mid-market, so its markup is zero and its whole cost
        # is the visible fee.
        wise = next(q for q in result.quotes if q.provider == "Wise")
        assert wise.fx_markup_pct == pytest.approx(0.0, abs=0.001)
        assert wise.total_cost == pytest.approx(wise.fee, abs=0.01)

    @pytest.mark.asyncio
    async def test_a_zero_fee_provider_still_shows_a_real_cost(self, live_providers):
        """
        Western Union's bank row advertises no fee at all, and is still the
        second most expensive option once the rate is accounted for. This is
        the number the headline fee hides.
        """
        result = await compare(req(pay_out_method="BANK_DEPOSIT", pay_in_method="BANK"))
        wu = next(q for q in result.quotes if q.provider == "Western Union")

        assert wu.fee == 0.0
        # 82.55 against a mid-market of 83.4210 is a ~1.04% markup.
        assert wu.fx_markup_pct == pytest.approx(1.04, abs=0.02)
        assert wu.total_cost > 10.0        # "free" costs more than Wise's 5.46 fee

    @pytest.mark.asyncio
    async def test_cheapest_may_select_a_non_bank_rail_and_labels_it(self, live_providers):
        """
        Asked purely for the most money, the engine will surface Western
        Union's cash-pickup row — it genuinely pays more than its bank row.
        That is a real answer, not a like-for-like violation, BECAUSE the
        payout rail is labelled and can be filtered on. The old code made the
        same choice silently, unlabelled, and without re-basing the fee.
        """
        result = await compare(req(sort_by=SortMode.CHEAPEST))
        wu = next(q for q in result.quotes if q.provider == "Western Union")

        assert wu.pay_out_method == "CASH_PICKUP"
        assert "Cash Pickup" in wu.transfer_time

        # And a user who wants bank-to-bank can simply ask for it.
        bank_only = await compare(req(pay_out_method="BANK_DEPOSIT"))
        wu_bank = next(q for q in bank_only.quotes if q.provider == "Western Union")
        assert wu_bank.pay_out_method == "BANK_DEPOSIT"
        assert wu_bank.receive_amount < wu.receive_amount

    @pytest.mark.asyncio
    async def test_no_provider_fails_when_the_reference_is_missing(self, monkeypatch):
        payload = {k: v for k, v in fixtures.WISE_COMPARISONS.items() if k != "midMarketRate"}
        original = httpx.AsyncClient

        def handler(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            if "wise" in host:
                return httpx.Response(200, json=payload)
            if "remitly" in host:
                return httpx.Response(200, json=fixtures.REMITLY_ESTIMATE)
            return httpx.Response(200, json=fixtures.WESTERN_UNION_CATALOG)

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        result = await compare(req())
        assert result.mid_market_rate is None
        assert all(q.fx_markup_pct is None for q in result.quotes)
        assert len(result.quotes) == 3       # markup is optional, quoting is not


class TestNoProviders:
    @pytest.mark.asyncio
    async def test_total_outage_explains_itself(self, monkeypatch):
        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(
                lambda r: httpx.Response(503, json={})
            )
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)

        with pytest.raises(ValueError, match="No provider returned a usable quote"):
            await compare(req())


class TestBadgesAreIndependentOfTheRequestedSort:
    """
    `best_by` must describe each provider at its OWN best under each mode.

    Badges used to be read off the already-selected result set, where every
    provider had been reduced to the option matching the REQUESTED sort. Ask
    for `cheapest` and the "Fastest" badge then named whichever provider's
    cheapest option happened to be quickest — not the genuinely fastest one.
    """

    @pytest.mark.asyncio
    async def test_fastest_badge_matches_an_actual_fastest_run(self, live_providers):
        cheapest_run = await compare(req(sort_by=SortMode.CHEAPEST))
        fastest_run = await compare(req(sort_by=SortMode.FASTEST))

        assert cheapest_run.best_by["fastest"] == fastest_run.best_provider.provider

    @pytest.mark.asyncio
    async def test_every_badge_is_stable_across_sort_modes(self, live_providers):
        runs = [await compare(req(sort_by=mode)) for mode in SortMode]
        assert all(r.best_by == runs[0].best_by for r in runs)

    @pytest.mark.asyncio
    async def test_each_badge_names_the_winner_of_its_own_mode(self, live_providers):
        badges = (await compare(req())).best_by
        for mode in SortMode:
            run = await compare(req(sort_by=mode))
            assert badges[mode.value] == run.best_provider.provider
