"""Lists of contracted EU projects, read without a database (fixtures cut by
research/eu-projects/cut_eu_fixtures.py from the real lists)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from date_romania.collectors.eu_projects.parse import (
    _amount,
    last_day,
    parse_payments,
    parse_projects,
    workbooks,
)

FIXTURES = Path(__file__).parent / "fixtures" / "eu_projects"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.mark.parametrize(
    ("label", "day"),
    [
        ("POR -Lista proiectelor contractate la 31 august 2025", date(2025, 8, 31)),
        ("PoAT: Lista proiectelor contractate la data de 31.12.2025", date(2025, 12, 31)),
        ("... Tranzitie Justa _PTJ_ la data de -30.06.2026", date(2026, 6, 30)),
        ("1 septembrie - 30 septembrie 2026", date(2026, 9, 30)),
        ("Lista proiectelor contractate", None),
    ],
)
def test_the_day_of_a_list_is_the_last_its_title_names(label, day):
    assert last_day(label) == day


def test_an_xlsx_is_one_workbook_and_archives_are_opened():
    assert [name for name, _ in workbooks(fixture("por.xlsx"))] == [""]
    # The zip holds the list and a pdf of it: only the workbook is read.
    assert [name for name, _ in workbooks(fixture("pddtj.zip"))] == ["Lista PDD la 30.06.2026.xlsx"]
    assert len(workbooks(fixture("pocidif.7z"))) == 2
    assert workbooks(b"%PDF-1.4") == []


def test_a_list_with_a_header_on_six_rows():
    parsed = parse_projects(fixture("por.xlsx"), "POR", "2014-2020", date(2025, 8, 31))
    assert parsed.rejected == []
    first = parsed.projects[0]
    assert (first["smis"], first["programme"], first["period"]) == (103910, "POR", "2014-2020")
    assert first["beneficiary_name"] == "ELEX-INTERNATIONAL S.R.L"
    assert first["beneficiary_cui"] is None
    assert first["total_value"] == Decimal("1048806.50")
    # The EU money in the eligible value, and paid: EU plus national money.
    assert first["eu_value"] == Decimal("597958.00")
    assert first["paid"] == Decimal("702645.51")
    assert first["county"] == "BACAU"
    assert first["cut_off"] == date(2025, 8, 31)


def test_a_2021_2027_list_gives_the_lead_cui_and_the_total_of_both_funds():
    parsed = parse_projects(fixture("poids.xlsx"), "PoIDS", "2021-2027", None)
    assert [row["beneficiary_cui"] for row in parsed.projects] == [47259371, 39382569, 18408844]
    third = parsed.projects[2]
    # Three groups of values (ESF+, ERDF, both): the total and the EU money of both.
    assert third["total_value"] == Decimal("14888772.35")
    assert third["eu_value"] == Decimal("5955508.94")
    assert all(cui in parsed.entities for cui in (47259371, 39382569, 18408844))


def test_the_list_sheet_is_the_one_with_titles_not_a_working_sheet():
    parsed = parse_projects(fixture("pddtj.zip"), "PDDTJ", "2021-2027", None)
    assert [row["smis"] for row in parsed.projects] == [321260, 321422, 321250]
    assert all(row["title"] for row in parsed.projects)


def test_every_workbook_of_an_archive_is_read():
    parsed = parse_projects(fixture("pocidif.7z"), "PoCIDIF", "2021-2027", None)
    assert len(parsed.projects) == 4


def test_a_cell_that_cannot_be_read_leaves_its_field_empty_and_is_counted(monkeypatch):
    parsed = parse_projects(fixture("por.xlsx"), "POR", "2014-2020", None)
    assert parsed.unread == {}
    from date_romania.collectors.eu_projects import parse

    real = parse._rate

    def two_rates(value):
        raise ValueError("'85% (RMPD) 80% (RMD)'")

    monkeypatch.setattr(parse, "_rate", two_rates)
    parsed = parse_projects(fixture("por.xlsx"), "POR", "2014-2020", None)
    assert len(parsed.projects) == 3
    assert parsed.unread == {"cofinancing_rate": 3}
    assert all(row["cofinancing_rate"] is None for row in parsed.projects)
    assert real("85%") == Decimal("0.8500") and real(0.6837) == Decimal("0.6837")


@pytest.mark.parametrize(
    ("written", "lei"),
    [
        ("12.500", Decimal("12500.00")),
        ("1.250.000", Decimal("1250000.00")),
        ("12.50", Decimal("12.50")),
        ("1.234.567,89", Decimal("1234567.89")),
        ("1,234,567.89", Decimal("1234567.89")),
        ("1234,5", Decimal("1234.50")),
        (1048806.5, Decimal("1048806.50")),
    ],
)
def test_amounts_in_either_convention(written, lei):
    assert _amount(written) == lei


def test_a_broken_archive_is_the_files_error():
    with pytest.raises(ValueError, match="unreadable archive"):
        workbooks(bytes.fromhex("377abcaf271c") + bytes(40))
    with pytest.raises(ValueError, match="unreadable archive"):
        workbooks(bytes.fromhex("504b0304") + b" not a zip")


def test_payments_one_by_one():
    parsed = parse_payments(fixture("ps_payments.xlsx"), "PS")
    assert parsed.found
    assert [(p["smis"], p["amount"], p["paid_on"]) for p in parsed.payments] == [
        (324809, Decimal("4700000.00"), date(2026, 9, 1)),
        (324809, Decimal("300000.00"), date(2026, 9, 1)),
        (324809, Decimal("1663800.00"), date(2026, 9, 1)),
    ]
    assert parsed.payments[0]["order_number"] == "2195"


def test_a_file_published_as_payments_that_holds_none_is_told_apart():
    parsed = parse_payments(fixture("ps_not_payments.xlsx"), "PS")
    assert (parsed.found, parsed.payments) == (False, [])
