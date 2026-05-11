from decimal import Decimal

from wallet_bot.utils.amounts import decimal_to_units, normalize_amount, units_to_decimal


def test_normalize_amount():
    assert normalize_amount("10") == Decimal("10.0000")
    assert normalize_amount("0.25") == Decimal("0.2500")


def test_units_conversion_roundtrip():
    value = Decimal("10.2500")
    units = decimal_to_units(value)
    assert units == 102500
    assert units_to_decimal(units) == Decimal("10.2500")
