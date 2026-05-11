from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from wallet_bot.constants import AMOUNT_SCALE
from decimal import Decimal, ROUND_HALF_UP


QUANTIZER = Decimal("0.0001")
SCALE_DECIMAL = Decimal(str(AMOUNT_SCALE))

SUFFIX_MULTIPLIERS = {
    "k": Decimal("1000"),
    "m": Decimal("1000000"),
    "b": Decimal("1000000000"),
}


def normalize_amount(raw: str) -> Decimal:
    # Validate user text input and normalize it to 4 decimals.
    # Supports suffixes like:
    # 10k = 10,000
    # 10m = 10,000,000
    # 2.5b = 2,500,000,000

    try:
        cleaned = raw.strip().lower().replace(",", "")
    except AttributeError:
        raise ValueError("Invalid amount. Use numbers like 10, 10.5, 0.25, 10k, 5m, 1b")

    if not cleaned:
        raise ValueError("Amount cannot be empty.")

    try:
        suffix = cleaned[-1]

        if suffix in SUFFIX_MULTIPLIERS:
            number_part = cleaned[:-1].strip()

            if not number_part:
                raise ValueError

            value = Decimal(number_part) * SUFFIX_MULTIPLIERS[suffix]
        else:
            value = Decimal(cleaned)

    except (InvalidOperation, ValueError):
        raise ValueError("Invalid amount. Use numbers like 10, 10.5, 0.25, 10k, 5m, 1b")

    if value < 0:
        raise ValueError("Negative amounts are not allowed.")

    return value.quantize(QUANTIZER, rounding=ROUND_HALF_UP)


def to_decimal(value: Decimal | int | float | str) -> Decimal:
    # Convert a supported value to a safe 4-decimal Decimal.
    return Decimal(str(value)).quantize(QUANTIZER, rounding=ROUND_HALF_UP)


def decimal_to_units(value: Decimal | int | float | str) -> int:
    # Convert a decimal amount into integer storage units.
    decimal_value = to_decimal(value)
    return int((decimal_value * SCALE_DECIMAL).to_integral_value(rounding=ROUND_HALF_UP))


def units_to_decimal(units: int | str) -> Decimal:
    # Convert integer storage units back into a 4-decimal Decimal.
    return (Decimal(int(units)) / SCALE_DECIMAL).quantize(QUANTIZER, rounding=ROUND_HALF_UP)


def fmt_amount(value: Decimal | int | float | str) -> str:
    return f"{to_decimal(value)}"


def fmt_units(units: int | str) -> str:
    return fmt_amount(units_to_decimal(int(units)))

def fmt_compact_amount(value: Decimal | int | float | str) -> str:
    val = to_decimal(value)
    abs_val = abs(val)

    def clean(num: Decimal) -> str:
        num = num.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return format(num, ".2f")

    if abs_val >= Decimal("1000000000"):
        return f"{clean(val / Decimal('1000000000'))}b"
    elif abs_val >= Decimal("1000000"):
        return f"{clean(val / Decimal('1000000'))}m"
    elif abs_val >= Decimal("1000"):
        return f"{clean(val / Decimal('1000'))}k"
    else:
        return clean(val)