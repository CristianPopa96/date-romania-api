from datetime import date

from date_romania.collectors.jobs import missing_days


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
