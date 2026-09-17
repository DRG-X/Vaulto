"""
delivery.py — structured delivery-time parsing.

Before this module, speed lived only as prose ("Within ~2 hours", "2-3 days",
"Express (Minutes)") and the UI ranked it by regex-matching that prose. That
cannot express "2 days beats 5 days", cannot filter on "arrives within an
hour", and silently reorders whenever a provider rewords a label.

Every provider does publish machine-readable timing; they just publish it in
three different shapes:

  Wise    ISO-8601 durations ("PT1H22M28.9S") or absolute delivery timestamps.
  Remitly A delivery-speed field plus the pay-in method (card funding settles
          in minutes, ACH takes days).
  WU      A `speed_indicator` that is either "0" (minutes) or a business-day
          range like "2-3".

This module converts all three into a single numeric range in minutes, and
renders the prose back out so the existing `transfer_time` field keeps
working for the frontend.

A note on business days: providers quoting "2-3 days" mean business days. We
store them as calendar-minute equivalents (1 day = 1440 min) purely so that
speeds are ORDERABLE against each other. That is exact enough for ranking and
filtering, and `eta_is_business_days` records which quotes were quoted that
way so the UI can say "business days" honestly.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Tuple

MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 24 * 60

EtaRange = Tuple[Optional[int], Optional[int]]

_ISO_DURATION_RE = re.compile(
    r"^P"
    r"(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?"
    r")?$",
    re.IGNORECASE,
)

# "2-3", "1 - 2", "3" ... optionally followed by a unit word.
_RANGE_RE = re.compile(
    r"^\s*(?P<lo>\d+(?:\.\d+)?)\s*(?:-|to|–)?\s*(?P<hi>\d+(?:\.\d+)?)?\s*"
    r"(?P<unit>minute|min|hour|hr|day|business day|week)?s?\s*$",
    re.IGNORECASE,
)


def iso8601_duration_to_minutes(raw: str) -> Optional[int]:
    """
    Convert an ISO-8601 duration to whole minutes, rounding UP.

    Rounding up is deliberate: a quote of "PT30S" is an arrival estimate, and
    promising 0 minutes would be a promise we cannot keep. One minute is the
    honest floor.
    """
    if not raw or not isinstance(raw, str):
        return None
    match = _ISO_DURATION_RE.match(raw.strip())
    if not match:
        return None

    parts = match.groupdict()
    if not any(parts.values()):
        return None

    total = 0.0
    total += float(parts["days"] or 0) * MINUTES_PER_DAY
    total += float(parts["hours"] or 0) * MINUTES_PER_HOUR
    total += float(parts["minutes"] or 0)
    total += float(parts["seconds"] or 0) / 60.0

    if total <= 0:
        return 0
    return max(1, int(total + 0.999999))


def _timestamp_to_minutes_from_now(raw: str, now: Optional[datetime] = None) -> Optional[int]:
    """Convert an absolute ISO timestamp into minutes from now (never negative)."""
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    reference = now or datetime.now(timezone.utc)
    delta_minutes = (parsed - reference).total_seconds() / 60.0
    if delta_minutes <= 0:
        return 0
    return int(delta_minutes + 0.999999)


def parse_wise_estimation(estimation: dict, now: Optional[datetime] = None) -> EtaRange:
    """
    Read Wise's `deliveryEstimation` block.

    Prefers the relative `duration` (stable, timezone-free). Falls back to the
    absolute `deliveryDate` timestamps, converted to minutes from now.
    """
    if not estimation or not isinstance(estimation, dict):
        return (None, None)

    duration = estimation.get("duration")
    if isinstance(duration, dict):
        lo = iso8601_duration_to_minutes(duration.get("min"))
        hi = iso8601_duration_to_minutes(duration.get("max"))
        if lo is not None or hi is not None:
            return _ordered(lo, hi)
    elif isinstance(duration, str):
        only = iso8601_duration_to_minutes(duration)
        if only is not None:
            return (only, only)

    delivery_date = estimation.get("deliveryDate")
    if isinstance(delivery_date, dict):
        lo = _timestamp_to_minutes_from_now(delivery_date.get("min"), now)
        hi = _timestamp_to_minutes_from_now(delivery_date.get("max"), now)
        if lo is not None or hi is not None:
            return _ordered(lo, hi)
    elif isinstance(delivery_date, str):
        only = _timestamp_to_minutes_from_now(delivery_date, now)
        if only is not None:
            return (only, only)

    return (None, None)


def parse_speed_indicator(raw) -> Tuple[Optional[int], Optional[int], bool]:
    """
    Read a Western Union `speed_indicator`.

    Returns (min_minutes, max_minutes, is_business_days).

    "0" means the money lands within minutes — WU's own UI renders it as
    "In minutes", so we model it as a 0-15 minute window rather than a literal
    zero, which would rank it ahead of a genuinely instant rail.
    """
    if raw is None:
        return (None, None, False)

    text = str(raw).strip()
    if not text:
        return (None, None, False)

    if text in ("0", "0-0"):
        return (0, 15, False)

    match = _RANGE_RE.match(text)
    if not match:
        return (None, None, False)

    lo_raw = match.group("lo")
    hi_raw = match.group("hi")
    unit = (match.group("unit") or "day").lower()

    if unit.startswith(("minute", "min")):
        scale, business = 1, False
    elif unit.startswith(("hour", "hr")):
        scale, business = MINUTES_PER_HOUR, False
    elif unit.startswith("week"):
        scale, business = 7 * MINUTES_PER_DAY, False
    else:
        scale, business = MINUTES_PER_DAY, True

    lo = int(float(lo_raw) * scale)
    hi = int(float(hi_raw) * scale) if hi_raw else lo
    lo, hi = _ordered(lo, hi)
    return (lo, hi, business)


def _ordered(lo: Optional[int], hi: Optional[int]) -> EtaRange:
    """Normalise a pair into (min, max), tolerating either side being absent."""
    if lo is None:
        return (hi, hi)
    if hi is None:
        return (lo, lo)
    return (lo, hi) if lo <= hi else (hi, lo)


def humanize(
    lo: Optional[int],
    hi: Optional[int],
    business_days: bool = False,
) -> str:
    """Render a minute range as the prose the UI shows."""
    if lo is None and hi is None:
        return "Unknown"
    if lo is None:
        lo = hi
    if hi is None:
        hi = lo

    day_word = "business day" if business_days else "day"

    if hi <= 15:
        return "Within minutes"
    if hi < MINUTES_PER_HOUR:
        return f"Within {hi} minutes"
    if hi < MINUTES_PER_DAY:
        lo_h = max(1, round(lo / MINUTES_PER_HOUR))
        hi_h = max(1, round(hi / MINUTES_PER_HOUR))
        if lo_h == hi_h:
            return f"Within ~{hi_h} hour{'s' if hi_h != 1 else ''}"
        return f"{lo_h}-{hi_h} hours"

    lo_d = max(1, round(lo / MINUTES_PER_DAY))
    hi_d = max(1, round(hi / MINUTES_PER_DAY))
    if lo_d == hi_d:
        return f"~{hi_d} {day_word}{'s' if hi_d != 1 else ''}"
    return f"{lo_d}-{hi_d} {day_word}s"


def sort_key(lo: Optional[int], hi: Optional[int]) -> tuple:
    """
    Ordering key for 'fastest first'.

    Sorts on the WORST case (max) before the best case, because a quote of
    "minutes to 3 days" is not faster than a reliable "2 hours". Quotes with
    no timing data sort last rather than winning by default.
    """
    if lo is None and hi is None:
        return (1, 0, 0)
    effective_hi = hi if hi is not None else lo
    effective_lo = lo if lo is not None else hi
    return (0, effective_hi, effective_lo)
