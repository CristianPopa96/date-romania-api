from datetime import UTC, date, timedelta

from date_romania.dates import day_bounds


def test_day_bounds_are_romanian_midnights():
    start, end = day_bounds(date(2026, 10, 6))
    assert start.isoformat() == "2026-10-06T00:00:00+03:00"
    assert end.isoformat() == "2026-10-07T00:00:00+03:00"
    # The day the clocks go back has 25 hours.
    start, end = day_bounds(date(2026, 10, 25))
    assert end.astimezone(UTC) - start.astimezone(UTC) == timedelta(hours=25)
