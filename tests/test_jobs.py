from datetime import UTC, date, timedelta

from date_romania.collectors.jobs import day_bounds, missing_days


def test_first_run_collects_only_the_last_day():
    assert missing_days(set(), date(2026, 10, 9)) == [date(2026, 10, 9)]


def test_missing_days_fills_every_gap_since_the_first_collected_day():
    done = {date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)}
    assert missing_days(done, date(2026, 10, 7)) == [
        date(2026, 10, 3),
        date(2026, 10, 4),
        date(2026, 10, 6),
        date(2026, 10, 7),
    ]


def test_missing_days_counts_from_the_first_day_tried():
    # The first run, for 1 Oct, failed: it is still due, with the days after it.
    assert missing_days(set(), date(2026, 10, 3), first=date(2026, 10, 1)) == [
        date(2026, 10, 1),
        date(2026, 10, 2),
        date(2026, 10, 3),
    ]
    assert missing_days({date(2026, 10, 2)}, date(2026, 10, 3), first=date(2026, 10, 1)) == [
        date(2026, 10, 1),
        date(2026, 10, 3),
    ]


def test_nothing_is_missing_when_up_to_date():
    assert missing_days({date(2026, 10, 9)}, date(2026, 10, 9)) == []


def test_day_bounds_are_romanian_midnights():
    start, end = day_bounds(date(2026, 10, 6))
    assert start.isoformat() == "2026-10-06T00:00:00+03:00"
    assert end.isoformat() == "2026-10-07T00:00:00+03:00"
    # The day the clocks go back has 25 hours.
    start, end = day_bounds(date(2026, 10, 25))
    assert end.astimezone(UTC) - start.astimezone(UTC) == timedelta(hours=25)
