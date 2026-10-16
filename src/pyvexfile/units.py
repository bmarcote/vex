"""Conversion of the values found in VEX files (frequencies, durations, epochs) into numbers.

All functions raise ValueError if the text does not have the expected format.
"""
from datetime import datetime, timedelta, timezone


__all__: list[str] = ["parse_frequency", "parse_duration", "parse_epoch"]

_FREQUENCY_UNITS: dict[str, float] = {"Hz": 1e-6, "kHz": 1e-3, "MHz": 1.0, "GHz": 1e3}
_TIME_UNITS: dict[str, float] = {"psec": 1e-12, "nsec": 1e-9, "usec": 1e-6, "msec": 1e-3,
                                 "sec": 1.0, "min": 60.0, "hr": 3600.0, "day": 86400.0,
                                 "yr": 365.25 * 86400.0}
_EPOCH_FIELDS = "ydhms"


def _split_quantity(text: str, units: dict[str, float], default: str | None) -> float:
    """Splits a value like '32.00 MHz' (or '32.00MHz') and returns it in the base unit."""
    text = text.strip()
    split = len(text)
    while split > 0 and text[split - 1].isalpha():
        split -= 1

    number, unit = text[:split].strip(), text[split:] or default
    if unit not in units:
        raise ValueError(f"unknown unit in '{text}' (expected one of: {', '.join(units)})")

    try:
        return float(number) * units[unit]
    except ValueError:
        raise ValueError(f"'{text}' is not a number followed by a unit") from None


def parse_frequency(text: str) -> float:
    """Returns the frequency in MHz of a value like '4632 MHz' or '32.00 MHz'."""
    return _split_quantity(text, _FREQUENCY_UNITS, None)


def parse_duration(text: str) -> float:
    """Returns the duration in seconds of a value like '360 sec' (seconds if no unit is given)."""
    return _split_quantity(text, _TIME_UNITS, "sec")


def parse_epoch(text: str) -> datetime:
    """Returns the UTC datetime of a VEX epoch like '2026y293d11h00m00s' or '1997y001d'.
    The year is mandatory; the remaining fields (day of year, hours, minutes, seconds) are optional.
    """
    invalid = f"'{text}' is not a valid VEX epoch (expected e.g. 2026y293d11h00m00s)"
    values: dict[str, float] = {}
    rest = text.strip()
    for field in _EPOCH_FIELDS:
        if not rest:
            break

        number, separator, after = rest.partition(field)
        if separator:
            try:
                values[field] = float(number)
            except ValueError:
                raise ValueError(invalid) from None

            rest = after

    if rest or "y" not in values:
        raise ValueError(invalid)

    epoch = datetime(int(values["y"]), 1, 1, tzinfo=timezone.utc)
    return epoch + timedelta(days=values.get("d", 1) - 1, hours=values.get("h", 0),
                             minutes=values.get("m", 0), seconds=values.get("s", 0))
