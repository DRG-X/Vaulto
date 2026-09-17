"""Structured delivery-time parsing and ordering."""

from datetime import datetime, timezone

import pytest

import delivery


class TestIsoDurations:
    @pytest.mark.parametrize("raw,minutes", [
        ("PT1H22M28.893687513S", 83),   # rounds up — a 28s tail is still time
        ("PT2H", 120),
        ("PT45M", 45),
        ("PT0S", 0),
        ("P1D", 1440),
        ("P2DT3H", 3060),
    ])
    def test_parses(self, raw, minutes):
        assert delivery.iso8601_duration_to_minutes(raw) == minutes

    @pytest.mark.parametrize("raw", ["", None, "garbage", "1H30M", "P"])
    def test_rejects_junk(self, raw):
        assert delivery.iso8601_duration_to_minutes(raw) is None

    def test_sub_minute_rounds_up_to_one(self):
        # Never promise "0 minutes" for something that takes 30 seconds.
        assert delivery.iso8601_duration_to_minutes("PT30S") == 1


class TestWiseEstimation:
    def test_reads_duration_range(self):
        assert delivery.parse_wise_estimation(
            {"duration": {"min": "PT0S", "max": "PT2H"}}
        ) == (0, 120)

    def test_falls_back_to_absolute_dates(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        estimation = {"deliveryDate": {
            "min": "2026-01-01T13:00:00Z",
            "max": "2026-01-02T12:00:00Z",
        }}
        assert delivery.parse_wise_estimation(estimation, now=now) == (60, 1440)

    def test_past_dates_clamp_to_zero_not_negative(self):
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        estimation = {"deliveryDate": {"min": "2026-01-01T00:00:00Z"}}
        assert delivery.parse_wise_estimation(estimation, now=now) == (0, 0)

    def test_empty_is_unknown_not_instant(self):
        assert delivery.parse_wise_estimation({}) == (None, None)
        assert delivery.parse_wise_estimation(None) == (None, None)


class TestSpeedIndicator:
    def test_zero_means_minutes_not_zero_days(self):
        assert delivery.parse_speed_indicator("0") == (0, 15, False)

    def test_business_day_range(self):
        assert delivery.parse_speed_indicator("2-3") == (2880, 4320, True)

    def test_single_day(self):
        assert delivery.parse_speed_indicator("1") == (1440, 1440, True)

    def test_explicit_units(self):
        assert delivery.parse_speed_indicator("30 minutes") == (30, 30, False)
        assert delivery.parse_speed_indicator("2 hours") == (120, 120, False)

    def test_unparseable_is_unknown(self):
        assert delivery.parse_speed_indicator("whenever") == (None, None, False)
        assert delivery.parse_speed_indicator(None) == (None, None, False)


class TestOrdering:
    def test_faster_sorts_first(self):
        assert delivery.sort_key(0, 15) < delivery.sort_key(0, 120)
        assert delivery.sort_key(0, 120) < delivery.sort_key(2880, 4320)

    def test_wide_range_does_not_beat_a_reliable_shorter_one(self):
        # "minutes to 3 days" must not outrank a dependable 2 hours.
        optimistic = delivery.sort_key(0, 4320)
        reliable = delivery.sort_key(120, 120)
        assert reliable < optimistic

    def test_unknown_timing_sorts_last(self):
        assert delivery.sort_key(None, None) > delivery.sort_key(10080, 10080)

    def test_string_sorting_would_have_been_wrong(self):
        # The old UI compared these as text, where "10" < "2".
        assert "10-12" < "2-3"
        assert delivery.sort_key(*delivery.parse_speed_indicator("2-3")[:2]) < \
               delivery.sort_key(*delivery.parse_speed_indicator("10-12")[:2])


class TestHumanize:
    @pytest.mark.parametrize("lo,hi,business,expected", [
        (0, 15, False, "Within minutes"),
        (0, 45, False, "Within 45 minutes"),
        (60, 120, False, "1-2 hours"),
        (120, 120, False, "Within ~2 hours"),
        (2880, 4320, True, "2-3 business days"),
        (1440, 1440, False, "~1 day"),
        (None, None, False, "Unknown"),
    ])
    def test_renders(self, lo, hi, business, expected):
        assert delivery.humanize(lo, hi, business) == expected
