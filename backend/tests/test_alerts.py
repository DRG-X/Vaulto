"""
Which quote an alert is actually watching.

`RateAlert.provider` was stored but never read: every alert fired on whichever
provider happened to be best. An alert set for "Wise at 55" would fire on
Remitly hitting 55 — a notification about a rate the user never asked to be
told about, on a provider they did not choose.
"""

from types import SimpleNamespace

import pytest

from scheduler import _quote_for_alert


def quote(provider, rate, pay_out="BANK_DEPOSIT"):
    return SimpleNamespace(provider=provider, exchange_rate=rate, pay_out_method=pay_out)


def alert(provider=None, pay_out_method=None):
    return SimpleNamespace(id=1, provider=provider, pay_out_method=pay_out_method)


def pools(*quotes):
    """Option pools keyed by provider, as `fetch_pools` returns them."""
    out = {}
    for q in quotes:
        out.setdefault(q.provider, []).append(q)
    return out


class TestProviderScoping:
    def test_an_unscoped_alert_watches_the_best_rate(self):
        r = pools(quote("Wise", 54.5), quote("Remitly", 54.1))
        assert _quote_for_alert(r, alert()).provider == "Wise"

    def test_a_scoped_alert_watches_only_that_provider(self):
        """The regression: this used to return Wise and fire on its rate."""
        r = pools(quote("Wise", 55.0), quote("Remitly", 54.1))
        picked = _quote_for_alert(r, alert(provider="Remitly"))

        assert picked.provider == "Remitly"
        assert picked.exchange_rate == 54.1

    def test_provider_matching_ignores_case_and_padding(self):
        r = pools(quote("Western Union", 54.0))
        assert _quote_for_alert(r, alert(provider="  western union ")) is not None

    def test_a_missing_provider_yields_nothing_not_a_fallback(self):
        # Falling back to the best quote is what caused the bug. Silence is the
        # honest answer when the watched provider did not quote.
        r = pools(quote("Wise", 55.0), quote("Remitly", 54.1))
        assert _quote_for_alert(r, alert(provider="OFX")) is None


class TestRailScoping:
    def test_an_alert_can_watch_one_rail(self):
        r = pools(
            quote("Remitly", 54.1, "BANK_DEPOSIT"),
            quote("Remitly", 53.9, "UPI"),
        )
        picked = _quote_for_alert(r, alert(provider="Remitly", pay_out_method="UPI"))
        assert picked.exchange_rate == 53.9

    def test_rail_matching_is_case_insensitive(self):
        r = pools(quote("Wise", 54.5, "BANK_DEPOSIT"))
        assert _quote_for_alert(r, alert(pay_out_method="bank_deposit")) is not None

    def test_a_missing_rail_yields_nothing(self):
        r = pools(quote("Wise", 54.5, "BANK_DEPOSIT"))
        assert _quote_for_alert(r, alert(pay_out_method="CASH_PICKUP")) is None

    def test_rail_without_provider_picks_the_best_on_that_rail(self):
        r = pools(
            quote("Wise", 54.5, "BANK_DEPOSIT"),
            quote("Western Union", 54.9, "CASH_PICKUP"),
        )
        picked = _quote_for_alert(r, alert(pay_out_method="CASH_PICKUP"))
        assert picked.provider == "Western Union"


class TestBackwardsCompatibility:
    def test_an_alert_row_without_the_new_column_still_works(self):
        # Rows predating the migration have no pay_out_method attribute at all.
        legacy = SimpleNamespace(id=7, provider="Wise")
        r = pools(quote("Wise", 54.5))
        assert _quote_for_alert(r, legacy).provider == "Wise"

    def test_no_quotes_at_all_is_handled(self):
        assert _quote_for_alert({}, alert()) is None


class TestRailAlertsSeeEveryOption:
    """
    The regression that made rail-scoped alerts useless.

    `compare()` collapses each provider to ONE option chosen by the active
    sort. An alert watching "Remitly via UPI" that looked at that result would
    only ever see Remitly's bank-deposit row and report "not available this
    round" forever — the rail it watches is in the pool but not in the output.
    """

    def test_a_rail_present_only_in_the_pool_is_still_found(self):
        # What a ranked comparison would have shown: bank deposit only.
        ranked_only = quote("Remitly", 54.1, "BANK_DEPOSIT")
        # What the pool actually holds.
        full_pool = pools(ranked_only, quote("Remitly", 53.9, "UPI"))

        picked = _quote_for_alert(full_pool, alert(provider="Remitly", pay_out_method="UPI"))
        assert picked is not None, "UPI option was in the pool but not found"
        assert picked.exchange_rate == 53.9

    def test_multiple_providers_each_keep_all_their_rails(self):
        full_pool = pools(
            quote("Wise", 54.5, "BANK_DEPOSIT"),
            quote("Remitly", 54.1, "BANK_DEPOSIT"),
            quote("Remitly", 53.9, "UPI"),
            quote("Western Union", 54.2, "CASH_PICKUP"),
        )
        assert _quote_for_alert(full_pool, alert(pay_out_method="UPI")).provider == "Remitly"
        assert _quote_for_alert(full_pool, alert(pay_out_method="CASH_PICKUP")).provider == "Western Union"
        # Unscoped still watches the best rate anywhere in the pool.
        assert _quote_for_alert(full_pool, alert()).provider == "Wise"
