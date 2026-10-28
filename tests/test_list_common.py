"""The parts every list of the list pattern shares; the purchases list tests them on data."""

from datetime import date

from sqlalchemy import column

from date_romania.api.routes.list_common import NamedFilters, step


def test_a_filter_is_left_out_by_its_name_and_the_rest_keep_their_order():
    filters = NamedFilters(
        {"q": column("a") == 1, "state": column("b") == 2, "cpv": column("c") == 3}
    )
    assert [str(each) for each in filters.all("state")] == ["a = :a_1", "c = :c_1"]
    assert len(filters.all()) == 3


def test_rows_spread_under_two_months_are_drawn_per_day():
    assert step(date(2026, 9, 1), date(2026, 10, 1)) == "day"
    assert step(date(2026, 8, 1), date(2026, 10, 2)) == "month"
    # Nothing found: months, the list's usual step.
    assert step(None, None) == "month"
