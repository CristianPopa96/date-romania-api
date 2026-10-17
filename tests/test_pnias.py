"""The Anghel Saligny payment files: reading them, and the rule that ties a payment to a
contract. The fixture is the file of 27 August 2026 cut to a few rows."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from date_romania import pnias_links
from date_romania.collectors.pnias import parse
from date_romania.collectors.pnias.parse import file_day, parse_payments
from date_romania.counties import county_name

FILE = (Path(__file__).parent / "fixtures" / "pnias_payments.xlsx").read_bytes()


@pytest.fixture(scope="module")
def payments():
    parsed = parse_payments(FILE, file_day("27 august 2026.xlsx"))
    assert parsed.rejected == []
    return {payment["id"]: payment for payment in parsed.payments}


def test_a_file_is_named_after_its_day():
    assert file_day("27 august 2026.xlsx") == date(2026, 8, 27)
    assert file_day("18 mai 2026.xlsx") == date(2026, 5, 18)
    assert file_day("Plati PNIAS") is None
    assert file_day(None) is None


def test_one_payment_per_request_from_both_sheets(payments):
    # Four requests for roads and water, one for gas. The pivot sheet and the totals row
    # under the gas table give none.
    assert sorted(payments) == [29409, 29779, 30437, 30677, 30695]
    assert {payment["network"] for payment in payments.values()} == {"infra", "gas"}
    assert payments[29779]["network"] == "gas"


def test_a_payment_keeps_what_the_file_says(payments):
    payment = payments[30695]
    assert payment["county"] == "SIBIU"
    assert payment["town_hall"] == "ȘEICA MARE"
    assert payment["project_id"] == 12519
    assert payment["amount"] == Decimal("986843.46")
    assert payment["total_value"] == Decimal("29990353.38")
    assert payment["ministry_contract_no"] == "3349"
    assert payment["ministry_contract_date"] == date(2024, 3, 14)
    assert payment["registered_on"] == date(2026, 8, 21)
    assert payment["published_on"] == date(2026, 8, 27)
    assert payment["progress"] == "83,34"
    assert payment["state"] == "Finalizată"
    assert (payment["builder_cui"], payment["designer_cui"]) == (33648158, 17131582)
    # Only the gas sheet says whether the EU programme also pays.
    assert payment["poim"] is None
    assert payments[29779]["poim"] is True


def test_a_tax_id_is_read_with_or_without_ro(payments):
    # 'RO23019533' and 'RO39245111' in the file.
    assert payments[30677]["builder_cui"] == 23019533
    assert payments[30677]["designer_cui"] == 39245111


def test_a_request_listed_twice_is_one_payment(payments):
    # 30437 is in the sheet with tax IDs and again in one without them, with the same
    # amount: the copies are merged, and what only one of them says is kept.
    payment = payments[30437]
    assert payment["town_hall"].startswith("Județul ALBA prin Consiliul")
    assert payment["amount"] == Decimal("2012.96")
    assert payment["designer_cui"] == 35747042
    assert payment["progress"] == "100%"


def test_a_row_that_is_not_a_finished_payment_is_set_aside():
    parsed = parse.Parsed()
    with pytest.raises(ValueError, match="no request number"):
        parse._payment({"annex": "fără număr", "county": "ALBA"}, "infra", None, parsed)
    request = {"annex": "ASA4-30001 / 21.08.2026 ora 10:00", "county": "ALBA"}
    with pytest.raises(ValueError, match="not finished"):
        parse._payment({**request, "state": "Respinsă"}, "infra", None, parsed)
    with pytest.raises(ValueError, match="cancelled or rejected"):
        parse._payment(
            {**request, "state": "Finalizată", "cancelled": "adresa 12.pdf"},
            "infra",
            None,
            parsed,
        )


@pytest.mark.parametrize(
    ("town_hall", "county", "buyer"),
    [
        ("ȘEICA MARE", "SIBIU", "COMUNA SEICA MARE (CONSILIUL LOCAL SEICA MARE)"),
        ("STÂLPENI", "ARGES", "COMUNA STALPENI ARGES"),
        ("JILAVELE", "IALOMITA", "COMUNA (PRIMARIA JILAVELE)"),
        ("CAJVANA", "SUCEAVA", "PRIMARIA ORASULUI CAJVANA - SUCEAVA"),
        ("DĂRĂȘTI-ILFOV", "ILFOV", "COMUNA DARASTI"),
        ("BÂRZAVA", "ARAD", "Comuna Birzava"),
        ("Județul ALBA prin Consiliul Județean", "ALBA", "JUDETUL ALBA"),
        ("Județul ALBA prin Consiliul Județean", "ALBA", "UAT JUDETUL ALBA"),
        ("Județul ALBA prin Consiliul Județean", "ALBA", "CONSILIUL JUDETEAN ALBA"),
    ],
)
def test_a_town_hall_is_found_under_the_names_seap_gives_it(town_hall, county, buyer):
    assert pnias_links.buyer_place(buyer, county) == pnias_links.payment_place(town_hall, county)


@pytest.mark.parametrize(
    ("town_hall", "county", "buyer"),
    [
        ("BUGHEA DE SUS", "ARGES", "COMUNA BUGHEA DE JOS"),
        # A town and its county share a name; they are not the same buyer.
        ("BUZĂU", "BUZAU", "JUDETUL BUZAU"),
        ("Județul BUZĂU prin Consiliul Județean", "BUZAU", "MUNICIPIUL BUZAU"),
        # An association of several communes is not the town hall.
        ("SUATU", "CLUJ", 'ASOCIATIA DE DEZVOLTARE INTERCOMUNITARA "CAIANU SUATU"'),
    ],
)
def test_another_buyer_is_not_taken_for_the_town_hall(town_hall, county, buyer):
    assert pnias_links.buyer_place(buyer, county) != pnias_links.payment_place(town_hall, county)


def test_counties_get_their_real_names():
    assert county_name("BISTRITA NASAUD") == "Bistrița-Năsăud"
    assert county_name("CARAS SEVERIN") == "Caraș-Severin"
    assert county_name("SIBIU") == "Sibiu"
    assert county_name("ELSEWHERE") == "ELSEWHERE"
    assert county_name(None) is None
