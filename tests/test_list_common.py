"""The parts every list of the list pattern shares, and the files lists are exported as;
the purchases list tests them on data."""

import asyncio
from datetime import date

from sqlalchemy import column

from date_romania.api.routes.common import CSV_CHUNK, cell, csv_file
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


def test_a_cell_that_could_start_a_formula_is_shown_as_text():
    for start in ("=", "+", "-", "@", chr(9), chr(13)):
        assert cell(f"{start}SUM(A1)") == f"'{start}SUM(A1)"
    assert cell("Primăria") == "Primăria"
    assert cell(None) is None


def test_a_file_is_sent_in_chunks_and_reads_back_whole():
    rows = ([n, f"row {n}"] for n in range(CSV_CHUNK * 2 + 5))
    response = csv_file(["n", "text"], rows, "test.csv")
    parts = asyncio.run(_read(response))
    # The mark, the header and a chunk of rows; a second chunk; the rest.
    assert len(parts) == 3
    lines = "".join(parts).removeprefix(chr(0xFEFF)).splitlines()
    assert lines[0] == "n,text"
    assert lines[-1] == f"{CSV_CHUNK * 2 + 4},row {CSV_CHUNK * 2 + 4}"
    assert len(lines) == CSV_CHUNK * 2 + 6


async def _read(response) -> list[str]:
    return [part async for part in response.body_iterator]
