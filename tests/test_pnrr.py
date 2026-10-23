"""The PNRR dashboard files, read without a database."""

import gzip
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from date_romania.collectors.pnrr.fetch import edition_of, editions, url_of
from date_romania.collectors.pnrr.parse import (
    ENDPOINTS,
    is_natural_person,
    measure_code,
    parse_contracts,
    parse_measures,
    parse_payments,
    parse_top,
    parse_totals,
    read,
    tie,
)
from date_romania.entities import kind_of

FIXTURES = Path(__file__).parent / "fixtures" / "pnrr"
DAY = date(2026, 10, 15)
# The cases the fixture holds (cut by research/eu-projects/cut_pnrr_fixture.py).
TWO_MEASURES, ONE, SEVERAL, PERSON = 2860682316, 1407901257, (3148101263, 4083808958), 627774206


def fixture(endpoint: str):
    return json.loads((FIXTURES / f"20261015-{endpoint}.json").read_text(encoding="utf-8"))


def test_read_takes_gzipped_or_plain_json():
    data = [{"a": 1}]
    assert read(gzip.compress(json.dumps(data).encode())) == data
    assert read(json.dumps(data).encode()) == data


def test_a_measure_is_named_by_its_codes():
    assert measure_code("C10", "I3", None) == "C10.I3"
    assert measure_code(" C10", "I3 ", "a") == "C10.I3.a"
    with pytest.raises(ValueError):
        measure_code("C10", None, None)


def test_a_contract_over_two_measures_has_two_lines_and_one_row():
    parsed = parse_contracts(fixture("progres_tehnic_proiecte"))
    assert parsed.rejected == []
    assert len(parsed.contracts) == 5
    lines = [line for line in parsed.lines if line["contract_id"] == TWO_MEASURES]
    assert [line["position"] for line in lines] == [1, 2]
    assert len({line["measure_code"] for line in lines}) == 2


def test_days_are_romanian_days():
    parsed = parse_contracts(fixture("progres_tehnic_proiecte"))
    one = next(each for each in parsed.contracts if each["id"] == ONE)
    # '2022-10-10T21:00:00Z' is 11 October in Bucharest.
    assert one["signed_on"] == date(2022, 10, 11)


def test_a_natural_person_is_kept_without_a_cui_and_never_an_entity():
    parsed = parse_contracts(fixture("progres_tehnic_proiecte"))
    person = next(each for each in parsed.contracts if each["id"] == PERSON)
    assert person["natural_person"] is True
    assert person["beneficiary_cui"] is None
    # Stored as published (Crispy, 22.10.2026); never served.
    assert person["beneficiary_name"] == "NUME FICTIV"
    assert all(name != "NUME FICTIV" for name, _ in parsed.entities.values())


@pytest.mark.parametrize(
    ("written", "natural"),
    [("PF", True), ("P.F.", True), ("Persoană fizică", True), ("PFA", False), ("UAT", False)],
)
def test_natural_persons_are_told_by_their_type(written, natural):
    assert is_natural_person(written) is natural


@pytest.mark.parametrize(
    ("written", "kind"),
    [
        ("UAT", "authority"),
        ("Unitate de învățământ", "authority"),
        ("SPITAL JUDETEAN", "authority"),
        ("DSP", "authority"),
        ("IMM", "company"),
        ("S.R.L.", "company"),
        ("ÎNTREPRINDERE MARE", "company"),
        ("MEDIC FAMILIE", "company"),
        ("ONG", "other"),
        (None, "other"),
    ],
)
def test_the_kind_of_a_beneficiary_comes_from_its_type(written, kind):
    assert kind_of(written) == kind


def test_payments_keep_alike_rows_and_their_order():
    parsed = parse_payments(fixture("plati_pnrr"))
    assert parsed.rejected == []
    assert [each["position"] for each in parsed.payments] == [1, 2, 3, 4]
    third, fourth = parsed.payments[2], parsed.payments[3]
    assert {k: v for k, v in third.items() if k != "position"} == {
        k: v for k, v in fourth.items() if k != "position"
    }
    assert all(isinstance(each["amount"], Decimal) for each in parsed.payments)


def test_a_payment_without_a_cui_is_flagged_as_a_possible_person():
    data = fixture("plati_pnrr")
    data[0]["cui_beneficiar_final"] = None
    first, second, *_ = parse_payments(data).payments
    assert (first["natural_person"], first["beneficiary_cui"]) == (True, None)
    assert second["natural_person"] is False


def test_a_payment_is_tied_only_to_the_one_contract_on_its_measure():
    contracts = parse_contracts(fixture("progres_tehnic_proiecte"))
    payments = parse_payments(fixture("plati_pnrr")).payments
    tie(payments, contracts.contracts, contracts.lines)
    tied, shared, alone, _ = payments
    assert (tied["contracts_on_measure"], tied["contract_id"]) == (1, ONE)
    assert (shared["contracts_on_measure"], shared["contract_id"]) == (2, None)
    assert (alone["contracts_on_measure"], alone["contract_id"]) == (0, None)


def test_measures_and_totals():
    measures = parse_measures(fixture("masuri"))
    assert measures.rejected == []
    assert len(measures.measures) == 6
    assert all(each["code"].startswith("C") for each in measures.measures)
    (totals,) = parse_totals(fixture("indicatori_total"), DAY).totals
    assert totals["day"] == DAY
    assert totals["contracts"] == 21710


def test_the_top_list_is_the_full_one_with_grants_and_loans_where_split():
    parsed = parse_top(fixture("top_beneficiari"), fixture("persons"))
    assert parsed.rejected == []
    assert len(parsed.top) == 3
    first = parsed.top[0]
    assert first["cui"] == 16054368
    assert first["grant"] is not None and first["loan"] is not None
    assert first["last_received_on"] == date(2026, 9, 25)
    third = parsed.top[2]
    assert third["total"] is not None


def test_an_edition_is_complete_only_with_every_file():
    files = [{"file": f"20261015-{endpoint}.json.gz"} for endpoint in ENDPOINTS]
    # An older edition, before the measures were published.
    files += [{"file": f"20260819-{e}.json.gz"} for e in ENDPOINTS if e != "masuri"]
    files += [{"file": "contains.json"}, {"file": "20261015-other.json.gz"}]
    found = editions({"files": files})
    assert [each.day for each in found] == [DAY]
    assert found[0].files["masuri"] == url_of(DAY, "masuri")
    assert edition_of(url_of(DAY, "plati_pnrr")) == (DAY, "plati_pnrr")
    assert edition_of("https://example.test/x.json.gz") is None
