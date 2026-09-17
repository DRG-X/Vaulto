"""
providers/scrapers/extract.py — pulling an FX rate out of a bank's rate page.

Banks publish their rates as an HTML table with no stable structure, no
versioning and no warning when it changes. Anything written here is a guess
about someone else's markup that will eventually be wrong. Two decisions
follow from that:

* **Several strategies, tried in order.** A table lookup, then a labelled
  value, then a last-resort proximity scan. One page rearranging its markup
  should degrade to the next strategy, not take the provider down.
* **Fail loudly, never plausibly.** Every function here returns None rather
  than a number it is unsure of. A scraper that returns a WRONG rate is far
  worse than one that returns nothing: nothing shows the provider as
  unavailable, while a wrong rate quietly ranks a bank as the best deal.

Rates are returned as Decimal, parsed from the page's own digits.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Sequence

from bs4 import BeautifulSoup

from money import ZERO

logger = logging.getLogger(__name__)

#: A plausible FX rate. Anything outside this is a page number, a phone
#: number, a year or a percentage that happened to sit near the currency code.
MIN_PLAUSIBLE_RATE = Decimal("0.000001")
MAX_PLAUSIBLE_RATE = Decimal("100000")

#: Digits, thousands commas, optional decimal part. Whitespace is NOT allowed
#: inside a number: with `\s` in the class, "1 57.50" (a unit column beside a
#: rate column, flattened into one string) parses as 157.50 — a plausible
#: wrong number, which is the worst thing this module can produce.
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def parse_number(text: str) -> Optional[Decimal]:
    """Extract the first decimal number from a cell, or None."""
    if not text:
        return None
    match = _NUMBER_RE.search(text.replace("\xa0", " "))
    if not match:
        return None
    cleaned = match.group(0).replace(",", "")
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def is_plausible_rate(value: Optional[Decimal]) -> bool:
    return (
        value is not None
        and value.is_finite()
        and MIN_PLAUSIBLE_RATE <= abs(value) <= MAX_PLAUSIBLE_RATE
        and value > ZERO
    )


def _cell_text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


#: Values a "per unit" column holds. A genuine FX rate is never EXACTLY one of
#: these — 1.0000 or 100.0000 to four decimal places does not happen — so they
#: are the signature of a unit column, not a rate.
_UNIT_LIKE = {Decimal(1), Decimal(10), Decimal(100), Decimal(1000)}


def _is_unit_like(value: Decimal) -> bool:
    return value == value.to_integral_value() and value in _UNIT_LIKE


def _header_rows(table) -> List[List[str]]:
    """
    Every header row in the table, each as its own list of labels.

    Flattening all `th` cells in a table (which an earlier version did) breaks
    on grouped headers. A rate card like

        | Currency |     Notes     |    Transfer    |
        |   Code   | Buy  |  Sell  | TT Buy | TT Sell |

    has a 3-cell outer row and a 5-cell inner row. Flattened, the hint "TT
    SELL" lands at index 7 of an 8-item list while the data row has 5 cells —
    so the index is meaningless and the code falls through to reading the CASH
    rate instead. Both are plausible numbers, so nothing downstream catches it.

    Keeping the rows separate lets `from_table` pick the one whose width
    actually matches the data row it is reading.
    """
    rows = []
    for row in table.find_all("tr"):
        headers = row.find_all("th")
        if headers:
            rows.append([_cell_text(th).upper() for th in headers])
    return rows


def _column_index_for(
    header_rows: List[List[str]],
    column_hints: Sequence[str],
    width: int,
) -> Optional[int]:
    """
    Index of the wanted column, using the header row that fits this data row.

    Only header rows of the same width as the data row are considered — an
    index taken from a row of a different shape points at a different column.
    """
    for headers in header_rows:
        if len(headers) != width:
            continue
        index = _match_column(headers, column_hints)
        if index is not None:
            return index
    return None


def from_table(
    html: str,
    currency_code: str,
    currency_names: Sequence[str] = (),
    column_hints: Sequence[str] = (),
) -> Optional[Decimal]:
    """
    Find the row for a currency and read the rate out of the right column.

    `column_hints` names the column we actually want — for a bank selling
    foreign currency that is the "TT selling" or "telegraphic transfer" rate,
    NOT the cash/notes rate, which is materially worse and would misprice the
    bank.

    When no hint matches we fall back to scanning the row, but only accept an
    UNAMBIGUOUS answer: exactly one plausible rate, after discarding unit
    columns. A rate card reading `AUD | 1 | 57.50` has two numbers in the row,
    and picking the first gives a rate of 1.0 — which, once inverted for the
    India-side providers, is still 1.0 and sails through every check. Refusing
    to guess is the only safe behaviour; the provider reports an error and the
    selector gets fixed in `sites.py`.
    """
    soup = BeautifulSoup(html, "html.parser")
    needles = [currency_code.upper(), *[n.upper() for n in currency_names]]

    for table in soup.find_all("table"):
        header_rows = _header_rows(table)

        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            texts = [_cell_text(c) for c in cells]
            joined = " | ".join(texts).upper()
            if not any(_mentions(joined, n) for n in needles):
                continue

            # Preferred: the column whose header matched a hint, resolved
            # against a header row of this row's own width.
            target_index = _column_index_for(header_rows, column_hints, len(texts))
            if target_index is not None and target_index < len(texts):
                value = parse_number(texts[target_index])
                if is_plausible_rate(value):
                    return value

            # Fallback: accept only an unambiguous single candidate.
            candidates = []
            for text in texts:
                value = parse_number(text)
                if value is None or not is_plausible_rate(value):
                    continue
                if _is_unit_like(value):
                    continue
                candidates.append(value)

            distinct = {c for c in candidates}
            if len(distinct) == 1:
                return candidates[0]
            if distinct:
                logger.warning(
                    "scrape: %s row has %d candidate rates %s and no matching "
                    "column header — refusing to guess; fix column_hints in sites.py",
                    currency_code, len(distinct), sorted(distinct),
                )
                return None

    return None


def _match_column(headers: List[str], hints: Sequence[str]) -> Optional[int]:
    """Index of the first header containing any hint, in hint priority order."""
    for hint in hints:
        needle = hint.upper()
        for index, header in enumerate(headers):
            if needle in header:
                return index
    return None


def _mentions(haystack: str, needle: str) -> bool:
    """
    Whole-token match for a currency code.

    A substring test would match "INR" inside "PRINTER" and, worse, "AUD"
    inside "FRAUD" — both of which appear on bank pages.
    """
    if not needle:
        return False
    return re.search(rf"(?<![A-Z]){re.escape(needle)}(?![A-Z])", haystack) is not None


def from_labelled_value(
    html: str,
    currency_code: str,
    currency_names: Sequence[str] = (),
) -> Optional[Decimal]:
    """
    Read a rate presented as a label/value pair rather than a table.

    Common on fintech rate widgets: "1 AUD = 54.23 INR".
    """
    soup = BeautifulSoup(html, "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split())
    needles = [currency_code.upper(), *[n.upper() for n in currency_names]]

    for needle in needles:
        # "1 AUD = 54.23 INR" / "AUD 54.23" / "AUD: 54.23"
        for pattern in (
            rf"(?<![A-Z]){re.escape(needle)}(?![A-Z])\s*[:=]?\s*({_NUMBER_RE.pattern})",
            rf"({_NUMBER_RE.pattern})\s*(?<![A-Z]){re.escape(needle)}(?![A-Z])",
        ):
            match = re.search(pattern, text.upper())
            if match:
                value = parse_number(match.group(1))
                if is_plausible_rate(value):
                    return value
    return None


def extract_rate(
    html: str,
    currency_code: str,
    currency_names: Sequence[str] = (),
    column_hints: Sequence[str] = (),
) -> Optional[Decimal]:
    """Try each strategy in order of reliability; None when all fail."""
    for strategy, args in (
        (from_table, (html, currency_code, currency_names, column_hints)),
        (from_labelled_value, (html, currency_code, currency_names)),
    ):
        try:
            value = strategy(*args)
        except Exception:
            logger.exception("scrape strategy %s raised", strategy.__name__)
            continue
        if is_plausible_rate(value):
            logger.info("scrape: %s found %s via %s", currency_code, value, strategy.__name__)
            return value
    return None
