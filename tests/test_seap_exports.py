"""SEAP's quarterly contract exports: three of the layouts, cut from the real files."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from date_romania.collectors.seap_exports import parse
from date_romania.collectors.seap_exports.parse import parse_contracts
from date_romania.collectors.seap_exports.run import chosen, is_contracts
from date_romania.collectors.sheets import csv_rows, is_workbook
from date_romania.text import plain

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT_2021 = (FIXTURES / "seap_export_2021.csv").read_bytes()
EXPORT_2022 = (FIXTURES / "seap_export_2022.csv").read_bytes()
EXPORT_2025 = (FIXTURES / "seap_export_2025.xlsx").read_bytes()

BAHM = 33648158


def test_the_signature_tells_a_workbook_from_text():
    assert is_workbook(EXPORT_2025)
    assert not is_workbook(EXPORT_2021)
    assert not is_workbook(EXPORT_2022)


def test_text_exports_are_split_whatever_separates_their_values():
    # Commas, with line breaks inside quoted values.
    assert [len(row) for row in csv_rows(EXPORT_2021)] == [36, 36, 36, 36]
    # Every value wrapped in `|`.
    rows = list(csv_rows(EXPORT_2022))
    assert [len(row) for row in rows] == [19, 19, 19, 19]
    assert rows[0][0] == "DENUMIRE_AC"
    assert list(csv_rows(b"a^b^c\n1^2^3\n")) == [["a", "b", "c"], ["1", "2", "3"]]


def test_headers_are_compared_without_case_and_diacritics():
    assert (
        plain("Număr anunț atribuire") == plain("NUMAR_ANUNT_ATRIBUIRE") == "NUMAR ANUNT ATRIBUIRE"
    )


def test_only_the_contracts_of_the_suppliers_asked_for_are_kept():
    parsed = parse_contracts(EXPORT_2025, {BAHM})
    # Six rows in the sheet; the sheet of notes at the end adds none.
    assert parsed.seen == 6
    assert parsed.rejected == []
    assert {row["notice_no"] for row in parsed.contracts} == {"SCNA1120751"}
    assert parse_contracts(EXPORT_2025, {12345674}).contracts == []


def test_an_association_keeps_a_row_for_every_member():
    rows = parse_contracts(EXPORT_2025, {BAHM}).contracts
    # The builder asked for is the second of four winners; all are kept, each with the
    # value of the whole contract.
    assert [row["supplier_cui"] for row in rows] == [23617561, BAHM, 3206081, 15440751]
    assert {row["value_ron"] for row in rows} == {Decimal("19583343")}
    assert {row["contract_no"] for row in rows} == {"2569/632"}


def test_every_buyer_of_an_export_is_noted_with_its_county_when_given():
    # Only the 2022 layout says where a buyer is.
    assert parse_contracts(EXPORT_2022, set()).buyers == {
        4288080: ("SPITALUL CLINIC JUDETEAN DE URGENTA CLUJ", "CLUJ")
    }
    assert parse_contracts(EXPORT_2025, set()).buyers == {
        4634256: ("SANATORIUL DE PNEUMOFTIZIOLOGIE BRAD", None),
        4241052: ("COMUNA SEICA MARE (CONSILIUL LOCAL SEICA MARE)", None),
    }


def test_a_contract_from_the_2025_layout():
    row = parse_contracts(EXPORT_2025, {BAHM}).contracts[1]
    assert row["buyer_text"] == "COMUNA SEICA MARE (CONSILIUL LOCAL SEICA MARE)"
    assert row["buyer_cui"] == 4241052
    assert row["supplier_text"] == "BAHM CONSTRUCTII CIVILE SI INDUSTRIALE"
    # Two columns are named "Data publicare"; the notice's is the one after its number.
    assert row["notice_date"] == date(2025, 5, 26)
    assert row["contract_date"] == date(2025, 5, 26)
    assert row["procedure_type"] == "Procedura simplificata"
    assert row["contract_type"] == "Lucrari"
    assert row["is_framework"] is False
    assert row["cpv_code"] == "45231300-8"
    assert row["lot"] == "1"
    assert row["title"] is None


def test_a_contract_from_the_2021_layout():
    parsed = parse_contracts(EXPORT_2021, {11147490})
    assert (parsed.seen, len(parsed.contracts), parsed.rejected) == (3, 1, [])
    row = parsed.contracts[0]
    assert row["supplier_text"] == "SANOFI ROMANIA S.R.L."
    assert row["notice_no"].startswith("CAN")
    assert row["title"]
    assert row["contract_type"] == "Furnizare"
    assert isinstance(row["contract_date"], date)
    assert row["buyer_cui"] == 3627501


def test_a_contract_from_the_2022_layout():
    # The winner's tax ID has a space in front, and the layout names no contract type.
    parsed = parse_contracts(EXPORT_2022, {23517392})
    assert (parsed.seen, parsed.rejected) == (3, [])
    # The notice has one contract per lot, each with its own number.
    row = next(row for row in parsed.contracts if row["supplier_cui"] == 23517392)
    assert row["notice_no"] == "CAN1069731"
    assert row["contract_date"] == date(2021, 12, 27)
    assert row["notice_date"] == date(2022, 1, 1)
    assert row["value_ron"] == Decimal("1293617")
    assert row["buyer_cui"] == 4288080
    assert row["title"] == "Consumabile - Masina pentru hemodializa acuta"
    assert row["contract_type"] is None
    assert row["is_framework"] is None


def test_dates_come_in_four_shapes():
    assert parse._day("7/1/2021") == date(2021, 7, 1)
    assert parse._day("12/27/2021") == date(2021, 12, 27)
    assert parse._day("09/21/2023 00:00:00") == date(2023, 9, 21)
    assert parse._day(datetime(2025, 5, 26, 14, 54, 8)) == date(2025, 5, 26)
    assert parse._day(date(2024, 9, 23)) == date(2024, 9, 23)
    # The second quarter of 2023 gives bare day numbers.
    assert parse._day(45007.0) == date(2023, 3, 22)
    assert parse._day(45017.45887731481) == date(2023, 4, 1)
    assert parse._day("") is None
    with pytest.raises(ValueError):
        parse._day("în curs")


def test_values_and_tax_ids_come_as_numbers_or_text():
    assert parse._money(19583343.0) == Decimal("19583343")
    assert parse._money("1293617") == Decimal("1293617")
    assert parse._money("1,293,617.50") == Decimal("1293617.50")
    assert parse._money("") is None
    assert parse._cui(4241052.0) == 4241052
    assert parse._cui("RO 23617561") == 23617561
    assert parse._cui(" 23517392") == 23517392
    assert parse._cui("") is None


def test_a_layout_without_the_winner_is_refused_out_loud():
    header = ["Autoritate contractanta", "Numar anunt atribuire", "Data contract"] + ["x"] * 9
    with pytest.raises(ValueError, match="no supplier_cui column"):
        parse._columns(header)
    # A row that only mentions the column is not a header: the sheet of notes has one.
    assert parse._columns(["Numar anunt atribuire", ""]) is None


def test_only_the_contracts_report_is_taken():
    assert is_contracts("Contracte 2021 - T1")
    assert is_contracts(" Contracte publicate T III 2024")
    assert is_contracts("Raport Contracte publicate T II 2024")
    assert not is_contracts("Date din modificare contract 2021 - T1")
    assert not is_contracts("Achizitii directe 2021 - T2")
    assert not is_contracts(None)


def test_a_quarter_published_twice_is_read_from_its_workbook():
    base = "https://data.gov.ro/dataset/x/resource"
    urls = [
        f"{base}/1/download/contracte-t-i-2024.xls",
        f"{base}/2/download/contracte-t-i-2024.csv",
        f"{base}/3/download/raport-contracte-t3.csv",
        f"{base}/4/download/contracte_tii.ods",
    ]
    assert chosen(urls) == [urls[0], urls[2], urls[3]]
