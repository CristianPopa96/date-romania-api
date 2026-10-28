"""The PNRR endpoints, over a small edition in a throwaway schema (see pnrr_seed.py)."""

import pnrr_seed
import pytest
from fastapi.testclient import TestClient
from pnrr_seed import FOREST, MANY_MEASURES, ONE, OTHER, PERSON, SEVERAL

from date_romania.api.main import app
from date_romania.db import get_session
from date_romania.models import Entity, PnrrContractLine

ROOT = "/v1/programmes/pnrr"


@pytest.fixture
def client(session):
    session.add_all(
        [
            Entity(cui=pnrr_seed.TOWN_HALL, name="Comuna Țânțăreni", kind="authority"),
            Entity(
                cui=pnrr_seed.HOSPITAL, name="SPITALUL JUDETEAN DE URGENTA CLUJ", kind="authority"
            ),
            Entity(cui=pnrr_seed.STATIONER, name="Beta Birotică SRL", kind="company"),
        ]
    )
    session.flush()
    pnrr_seed.seed(session)
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_programme_is_one_edition_with_its_measures_and_top_recipients(client):
    answer = client.get(ROOT).json()
    assert answer["edition"] == "2026-10-15"
    assert (answer["allocated_eur"], answer["paid_eur"]) == (20106860700.0, 14939205346.68)
    # Contracted is published in lei only: the measures added up.
    assert answer["contracted_ron"] == 3250000000.0
    by_code = {m["code"]: m for m in answer["measures"]}
    assert by_code["C10.I3"]["contracts"] == 3
    assert by_code["C2.I1"]["contracts"] == 2
    assert [t["cui"] for t in answer["top"]] == [pnrr_seed.TOWN_HALL, pnrr_seed.HOSPITAL]
    assert answer["top"][0]["entity"]["kind"] == "authority"
    assert (answer["source"]["record"], answer["source"]["documents"]) == (
        "Tabloul de bord PNRR",
        5,
    )


def test_a_measure_counts_natural_persons_and_what_was_paid_without_a_contract(client):
    measure = client.get(f"{ROOT}/measures/c2.i1").json()
    assert measure["code"] == "C2.I1"
    assert (measure["contracts"], measure["natural_persons"]) == (2, 1)
    assert (measure["paid_without_contract"], measure["payments_without_contract"]) == (50000.0, 1)
    # The natural person's county is not listed: it would point at a person.
    assert measure["counties"] == ["GORJ"]
    assert client.get(f"{ROOT}/measures/C99.I9").status_code == 404


def test_contracts_never_list_natural_persons_and_say_how_many_were_left_out(client):
    page = client.get(f"{ROOT}/contracts", params={"measure": "C2.I1"}).json()
    assert [row["id"] for row in page["items"]] == [FOREST]
    assert (page["total"], page["natural_persons"]) == (1, 1)
    assert "NUME FICTIV" not in str(page)


def test_contracts_are_the_largest_first_with_filters(client):
    page = client.get(f"{ROOT}/contracts").json()
    assert [row["id"] for row in page["items"]] == [ONE, SEVERAL, OTHER, MANY_MEASURES, FOREST]
    finished = client.get(f"{ROOT}/contracts", params={"status": "finished"}).json()
    assert [row["id"] for row in finished["items"]] == [OTHER]
    # A contract's status is the one all its measures give: one whose measures differ is
    # under none, as its row says ("pe măsuri").
    under = client.get(f"{ROOT}/contracts", params={"status": "under_30"}).json()
    assert [row["id"] for row in under["items"]] == []
    rows = {row["id"]: row for row in page["items"]}
    assert (rows[MANY_MEASURES]["status"], rows[MANY_MEASURES]["measures_differ"]) == (None, True)
    assert (rows[ONE]["status"], rows[ONE]["measures_differ"]) == ("in_progress", False)
    found = client.get(f"{ROOT}/contracts", params={"q": "spitalul"}).json()
    assert {row["id"] for row in found["items"]} == {SEVERAL, OTHER}
    gorj = client.get(f"{ROOT}/contracts", params={"county": "GORJ", "measure": "C10.I3"}).json()
    assert [row["id"] for row in gorj["items"]] == [ONE]


def test_a_contract_alone_on_its_measure_has_the_payments_as_its_own(client):
    contract = client.get(f"{ROOT}/contracts/{ONE}").json()
    assert (contract["number"], contract["status"]) == ("12321", "in_progress")
    assert (contract["physical_progress"], contract["financial_progress"]) == (0.4, 0.35)
    assert contract["measures_differ"] is False
    assert contract["beneficiary"]["cui"] == pnrr_seed.TOWN_HALL
    (paid,) = contract["payments"]
    assert (paid["contracts"], paid["count"], paid["paid"]) == (1, 3, 2300000.0)
    assert [p["paid_on"] for p in paid["items"]] == ["2026-10-02", "2026-06-11", "2025-12-19"]
    assert paid["others"] == []
    assert (contract["source"]["sha256"], contract["source"]["parser_version"]) == ("6" * 64, 1)


def test_payments_to_a_beneficiary_with_several_contracts_belong_to_none(client):
    contract = client.get(f"{ROOT}/contracts/{SEVERAL}").json()
    (paid,) = contract["payments"]
    assert (paid["contracts"], paid["count"], paid["paid"]) == (2, 2, 1800000.0)
    assert [other["id"] for other in paid["others"]] == [OTHER]


def test_a_contract_on_measures_that_disagree_gives_each_its_own(client):
    contract = client.get(f"{ROOT}/contracts/{MANY_MEASURES}").json()
    assert contract["total"] == 1416076.55
    assert (contract["status"], contract["physical_progress"]) == (None, None)
    assert contract["measures_differ"] is True
    assert [(line["measure"], line["status"]) for line in contract["lines"]] == [
        ("C15.I11", "in_progress"),
        ("C15.I9", "under_30"),
    ]
    paid = {each["measure"]: each for each in contract["payments"]}
    assert (paid["C15.I11"]["count"], paid["C15.I9"]["count"]) == (1, 0)
    # A personal code typed into the title is masked.
    assert contract["title"] == "Dotări școlare Beta [CNP]"


def test_a_value_nobody_published_is_not_a_disagreement(client, session):
    line = session.get(PnrrContractLine, (FOREST, 1))
    line.physical_progress = None
    session.flush()
    rows = {row["id"]: row for row in client.get(f"{ROOT}/contracts").json()["items"]}
    assert (rows[FOREST]["physical_progress"], rows[FOREST]["measures_differ"]) == (None, False)
    assert client.get(f"{ROOT}/contracts/{FOREST}").json()["measures_differ"] is False


def test_a_blank_measure_does_not_make_the_list_and_the_page_disagree(client, session):
    """Two measures, one with progress and one blank: one figure, in both answers."""
    blank = session.get(PnrrContractLine, (MANY_MEASURES, 2))
    blank.physical_progress, blank.financial_progress = None, None
    blank.status = "ÎN IMPLEMENTARE"
    session.flush()
    rows = {row["id"]: row for row in client.get(f"{ROOT}/contracts").json()["items"]}
    page = client.get(f"{ROOT}/contracts/{MANY_MEASURES}").json()
    assert (rows[MANY_MEASURES]["physical_progress"], rows[MANY_MEASURES]["measures_differ"]) == (
        0.9529,
        False,
    )
    assert (page["physical_progress"], page["financial_progress"]) == (0.9529, 0.9019)
    assert (page["status"], page["measures_differ"]) == ("in_progress", False)


def test_a_natural_persons_contract_has_no_page(client):
    assert client.get(f"{ROOT}/contracts/{PERSON}").status_code == 404
    assert client.get(f"{ROOT}/contracts/1").status_code == 404


def test_a_beneficiarys_contracts_filter_and_sort_over_the_whole_list(client):
    def ids(**params):
        page = client.get(f"{ROOT}/contracts", params={"beneficiary": pnrr_seed.HOSPITAL, **params})
        return [row["id"] for row in page.json()["items"]]

    assert ids() == [SEVERAL, OTHER]
    assert ids(sort="progress") == [OTHER, SEVERAL]
    assert ids(sort="value", order="asc") == [OTHER, SEVERAL]
    assert ids(status=["finished", "under_30"]) == [OTHER]
    assert ids(progress_min=1) == [OTHER]
    assert ids(progress_max=0.75) == [SEVERAL]
    assert ids(value_max=2_000_000) == [OTHER]
    assert ids(measure=["C10.I3"]) == [SEVERAL, OTHER]
    assert ids(q="ambulatoriu") == [OTHER]


def test_a_beneficiarys_contracts_say_what_their_filters_keep(client):
    def overview(**params):
        return client.get(f"{ROOT}/contracts/overview", params=params).json()

    hospital = overview(beneficiary=pnrr_seed.HOSPITAL, scope="beneficiary")
    assert hospital["summary"] == {"contracts": 2, "value": 4350000, "natural_persons": 0}
    assert hospital["whole"] == 2
    assert hospital["measures"] == [{"value": "C10.I3", "count": 2}]
    assert [(s["value"], s["count"]) for s in hospital["statuses"]] == [
        ("in_progress", 1),
        ("under_30", 0),
        ("finished", 1),
    ]
    assert hospital["measures_differ"] == 0
    assert [(b["start"], b["count"]) for b in hospital["progress"]] == [
        (0, 0),
        (0.25, 0),
        (0.5, 1),
        (0.75, 0),
        (1, 1),
    ]

    # Measures that disagree: under no status, counted apart.
    stationer = overview(beneficiary=pnrr_seed.STATIONER, scope="beneficiary")
    assert stationer["measures_differ"] == 1
    assert all(s["count"] == 0 for s in stationer["statuses"])

    # A natural person's contract is counted, never listed.
    forests = overview(measure="C2.I1")
    assert (forests["summary"]["contracts"], forests["summary"]["natural_persons"]) == (1, 1)

    empty = overview(beneficiary=pnrr_seed.HOSPITAL, status="finished", value_min=5_000_000)
    assert empty["summary"]["contracts"] == 0
    assert empty["without"] == [
        {"param": "status", "count": 0},
        {"param": "beneficiary", "count": 0},
        {"param": "value_min", "count": 1},
    ]
