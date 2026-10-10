from datetime import date

from date_romania.collectors.jobs import collect_days, due_days, missing_days


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


def test_due_days_for_one_day_or_a_range_needs_no_history():
    assert due_days(None, "job", date(2026, 10, 9), day=date(2026, 10, 1)) == [date(2026, 10, 1)]
    assert due_days(None, "job", date(2026, 10, 3), since=date(2026, 10, 2)) == [
        date(2026, 10, 2),
        date(2026, 10, 3),
    ]
    assert due_days(None, "job", date(2026, 10, 3), since=date(2026, 10, 5)) == []


def test_collect_days_reports_each_day_and_returns_the_failed_ones():
    reported = []

    def collect_day(day):
        if day.day == 2:
            raise RuntimeError("the source answered nonsense")
        return day.day

    failed = collect_days(
        [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)],
        collect_day,
        lambda day, count: reported.append((day, count)),
    )

    assert failed == [date(2026, 10, 2)]
    assert reported == [(date(2026, 10, 1), 1), (date(2026, 10, 3), 3)]
