"""Precision guarantees of the Decimal money core."""

from decimal import Decimal

import pytest

from money import (
    D,
    currency_exponent,
    floor_money,
    percent_of,
    quantize_money,
    quantize_rate,
    to_float,
    to_str,
)


class TestParsing:
    def test_strings_keep_their_exact_digits(self):
        # The whole point: a provider's published rate survives verbatim.
        assert D("83.4210") == Decimal("83.4210")
        assert str(D("83.4210")) == "83.4210"

    def test_floats_do_not_inherit_binary_noise(self):
        # Decimal(0.1) is 0.1000000000000000055511151231257827...
        assert D(0.1) == Decimal("0.1")
        assert D(83.421) == Decimal("83.421")

    def test_thousands_separators_and_blanks(self):
        assert D("1,234.56") == Decimal("1234.56")
        assert D("") == Decimal("0")
        assert D(None) == Decimal("0")
        assert D("not a number") == Decimal("0")

    def test_default_is_honoured_for_missing_values(self):
        assert D(None, default=None) is None
        assert D("", default=None) is None

    def test_booleans_are_not_treated_as_numbers(self):
        # bool subclasses int; True must not silently become a fee of 1.
        assert D(True) == Decimal("0")


class TestCurrencyExponents:
    @pytest.mark.parametrize("code,expected", [
        ("USD", 2), ("INR", 2), ("EUR", 2),
        ("JPY", 0), ("KRW", 0), ("VND", 0), ("CLP", 0),
        ("KWD", 3), ("BHD", 3), ("OMR", 3),
    ])
    def test_iso_minor_units(self, code, expected):
        assert currency_exponent(code) == expected

    def test_zero_decimal_currency_is_not_given_cents(self):
        # 12345.678 yen is 12346 yen, not 12345.68.
        assert quantize_money(D("12345.678"), "JPY") == Decimal("12346")

    def test_three_decimal_currency_keeps_all_three(self):
        assert quantize_money(D("12.3456"), "KWD") == Decimal("12.346")


class TestRounding:
    def test_half_up_not_bankers_rounding(self):
        # Python's round() gives 2.67 here; payment providers give 2.68.
        assert quantize_money(D("2.675"), "USD") == Decimal("2.68")
        assert quantize_money(D("2.665"), "USD") == Decimal("2.67")

    def test_rounding_is_symmetric_for_negatives(self):
        assert quantize_money(D("-2.675"), "USD") == Decimal("-2.68")

    def test_floor_never_rounds_up(self):
        # Used to derive a principal that must fit inside a budget.
        assert floor_money(D("996.019"), "USD") == Decimal("996.01")
        assert floor_money(D("996.999"), "USD") == Decimal("996.99")

    def test_rate_precision_survives(self):
        assert quantize_rate(D("83.42106789")) == Decimal("83.4210678900")


class TestBoundaryConversion:
    def test_quantized_decimals_round_trip_through_float(self):
        for raw in ["83002.55", "0.01", "1234567.89", "83.4210"]:
            value = D(raw)
            assert Decimal(str(to_float(value))) == value

    def test_to_str_never_uses_scientific_notation(self):
        assert to_str(Decimal("1000")) == "1000"
        assert to_str(Decimal("1E+3")) == "1000"
        assert to_str(Decimal("0.00001")) == "0.00001"

    def test_percent_of_guards_division_by_zero(self):
        assert percent_of(D("5"), D("0")) is None
        assert percent_of(D("5.46"), D("1000")) == Decimal("0.5460")


def test_float_arithmetic_actually_drifts():
    """
    The bug this module exists to prevent, demonstrated.

    Accumulating a fee 100 times in float leaves a residue; in Decimal it
    does not. Small per-quote, systematic across a comparison.
    """
    as_float = sum(0.1 for _ in range(100))
    assert as_float != 10.0

    as_decimal = sum(D("0.1") for _ in range(100))
    assert as_decimal == Decimal("10.0")
