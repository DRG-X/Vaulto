"""
money.py — Decimal-exact money primitives for Flint.

Why this module exists
----------------------
Every provider quote is money, and money is decimal, not binary. Doing
`amount * rate` in IEEE-754 floats and then calling `round(x, 2)` introduces
two distinct errors:

  1. Representation error. 83.421 has no exact binary form, so the product
     drifts in the last places before it is ever rounded.
  2. Rounding mode. Python's built-in `round()` is round-half-to-EVEN
     (banker's rounding). Payment providers quote with round-half-UP. On a
     value landing exactly on a half-cent the two disagree by one minor unit.

Neither error is large on its own, but they compound across
`fee -> principal -> rate -> receive amount` and they are systematic, so the
same provider is biased the same way on every quote. That is enough to flip
the winner of a comparison when two providers are close.

The rules this module enforces
------------------------------
* Parse provider numbers from their ORIGINAL STRING form wherever the wire
  gives us one. `Decimal("83.4210")` keeps exactly what the provider said;
  `Decimal(float("83.4210"))` does not.
* Never let a float touch a monetary value in between. Floats appear only at
  the JSON boundary, after quantization, where the value has few enough
  decimals to round-trip exactly.
* Quantize to the currency's real ISO 4217 minor unit. JPY has no decimal
  places and KWD has three; rounding either to 2 dp is wrong.
* Round half-up, the way payment providers do.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, InvalidOperation
from typing import Any, Optional

# ---------------------------------------------------------------------------
# ISO 4217 minor units (only the non-2 exceptions are listed)
# ---------------------------------------------------------------------------

#: Currencies with no minor unit. Rounding these to 2 dp invents precision
#: that the payout rail cannot deliver — you cannot receive 0.42 yen.
ZERO_DECIMAL_CURRENCIES = frozenset({
    "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW",
    "PYG", "RWF", "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF",
})

#: Currencies with three minor units.
THREE_DECIMAL_CURRENCIES = frozenset({
    "BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND",
})

DEFAULT_CURRENCY_EXPONENT = 2

#: Exchange rates are kept far wider than any currency. Providers publish
#: rates to 5-7 significant decimals; 10 keeps every digit they send plus
#: headroom for intermediate maths.
RATE_DECIMAL_PLACES = 10

#: Percentages (markup, total cost) are reported to 4 dp — enough to show a
#: 0.0001% difference between two near-identical providers.
PERCENT_DECIMAL_PLACES = 4

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


def currency_exponent(currency: str) -> int:
    """Return the number of minor-unit decimal places for an ISO 4217 code."""
    if not currency:
        return DEFAULT_CURRENCY_EXPONENT
    code = currency.strip().upper()
    if code in ZERO_DECIMAL_CURRENCIES:
        return 0
    if code in THREE_DECIMAL_CURRENCIES:
        return 3
    return DEFAULT_CURRENCY_EXPONENT


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

#: Distinguishes "caller did not specify a default" from "caller explicitly
#: wants None back". Without it, `D(x, default=None)` reads as "give me None
#: when this field is missing" but silently yields Decimal(0) — and a zero fee
#: is a very different claim from an absent one.
_UNSET = object()


def D(value: Any, default: Any = _UNSET) -> Optional[Decimal]:
    """
    Coerce a provider-supplied value into an exact Decimal.

    Strings go straight to Decimal so the provider's own digits survive.
    Floats are routed through `repr()` — `Decimal(str(0.1))` is `0.1`, whereas
    `Decimal(0.1)` is 0.1000000000000000055511151231257827021181583404541015625.
    That only recovers what the float already lost, which is exactly why
    callers should pass strings when the wire had strings.

    Missing, empty and unparseable input yields 0 by default, so an absent
    optional field never raises mid-quote. Pass `default=None` for fields
    where absence is meaningful — a provider that published no receive amount
    must not be recorded as having published zero.
    """
    fallback = ZERO if default is _UNSET else default

    if value is None:
        return fallback
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):          # bool is an int subclass; reject it
        return fallback
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return fallback
        try:
            return Decimal(text)
        except InvalidOperation:
            return fallback
    return fallback


def is_finite(value: Optional[Decimal]) -> bool:
    """True when the value is a usable finite Decimal (not None/NaN/Inf)."""
    return isinstance(value, Decimal) and value.is_finite()


# ---------------------------------------------------------------------------
# Quantization
# ---------------------------------------------------------------------------

def quantize_money(amount: Decimal, currency: str) -> Decimal:
    """Round a monetary amount half-up to its currency's minor unit."""
    exponent = currency_exponent(currency)
    quantum = Decimal(1).scaleb(-exponent)     # 1, 0.01 or 0.001
    return amount.quantize(quantum, rounding=ROUND_HALF_UP)


def quantize_rate(rate: Decimal, places: int = RATE_DECIMAL_PLACES) -> Decimal:
    """Round an exchange rate half-up to a fixed, generous precision."""
    return rate.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def quantize_percent(pct: Decimal, places: int = PERCENT_DECIMAL_PLACES) -> Decimal:
    """Round a percentage half-up."""
    return pct.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def floor_money(amount: Decimal, currency: str) -> Decimal:
    """
    Round a monetary amount DOWN to its currency's minor unit.

    Used where over-stating would mislead — e.g. deriving the principal a
    fee-on-top provider will actually convert, where rounding up could claim
    the sender converts more than their budget covers.
    """
    exponent = currency_exponent(currency)
    quantum = Decimal(1).scaleb(-exponent)
    return amount.quantize(quantum, rounding=ROUND_DOWN)


# ---------------------------------------------------------------------------
# Boundary conversion
# ---------------------------------------------------------------------------

def to_float(value: Optional[Decimal]) -> Optional[float]:
    """
    Convert an ALREADY-QUANTIZED Decimal to float for JSON output.

    Safe only because the input has at most a handful of decimal places and a
    magnitude well inside 2**53, so the float round-trips to the same decimal
    string. Never call this on an intermediate value.
    """
    if value is None:
        return None
    if not is_finite(value):
        return None
    return float(value)


def to_str(value: Optional[Decimal]) -> Optional[str]:
    """Render a Decimal as a plain (non-scientific) string for exact transport."""
    if value is None or not is_finite(value):
        return None
    normalized = value.normalize()
    sign, digits, exponent = normalized.as_tuple()
    # `normalize()` turns 1000 into 1E+3; expand it back for JSON consumers.
    if isinstance(exponent, int) and exponent > 0:
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


def percent_of(part: Decimal, whole: Decimal) -> Optional[Decimal]:
    """Return `part` as a percentage of `whole`, or None when undefined."""
    if not is_finite(part) or not is_finite(whole) or whole == ZERO:
        return None
    return quantize_percent(part / whole * HUNDRED)
