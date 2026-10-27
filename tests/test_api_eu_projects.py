"""The EU cohesion project endpoints, over a few projects in a throwaway schema (see
eu_seed.py)."""

import eu_seed
import pytest
from eu_seed import HEALTH, PEO, POCU, POIM, POR
from fastapi.testclient import TestClient

from date_romania.api.main import app
from date_romania.db import get_session
from date_romania.models import Entity

ROOT = "/v1/programmes/eu-funds"


@pytest.fixture
def client(session):
    session.add_all(
        [
            Entity(cui=eu_seed.TOWN_HALL, name="Comuna Țânțăreni", kind="authority"),
            Entity(cui=eu_seed.HOSPITAL, name="SPITALUL JUDETEAN DE URGENTA", kind="authority"),
        ]
    )
    session.flush()
    eu_seed.seed(session)
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_each_programme_is_counted_from_its_own_list(client):
    answer = client.get(ROOT).json()
    assert [p["code"] for p in answer["programmes"]] == ["POR", "POIM", "POCU", "PEO", "PS"]
    pocu = answer["programmes"][2]
    assert (pocu["name"], pocu["period"]) == ("Programul Operațional Capital Uman", "2014-2020")
    # POCU publishes no total value: nothing is made up for it.
    assert (pocu["projects"], pocu["total"], pocu["paid"]) == (1, None, 400000.0)
    assert answer["programmes"][3]["cut_off"] == "2026-09-30"
    assert answer["source"]["documents"] == 3


def test_projects_the_largest_first_with_how_their_beneficiary_is_tied(client):
    page = client.get(f"{ROOT}/projects").json()
    assert page["total"] == 5
    assert [p["smis"] for p in page["items"]] == [POIM, POR, HEALTH, PEO, POCU]
    by_smis = {p["smis"]: p for p in page["items"]}
    assert by_smis[PEO]["beneficiary"]["confidence"] == "sure"
    assert by_smis[POR]["beneficiary"]["entity"]["cui"] == eu_seed.TOWN_HALL
    assert by_smis[POR]["beneficiary"]["confidence"] == "probable"
    assert by_smis[POR]["beneficiary"]["method"] == "administration-name+place"
    assert by_smis[POCU]["beneficiary"] == {
        "name": "ASOCIATIA PENTRU EDUCATIE DIGITALA",
        "entity": None,
        "confidence": None,
        "method": None,
    }


@pytest.mark.parametrize(
    ("query", "found"),
    [
        ("programme=POR", [POR]),
        (f"beneficiary={eu_seed.HOSPITAL}", [HEALTH, PEO]),
        ("status=in_progress", [HEALTH, PEO]),
        ("status=finished", [POR]),
        ("status=terminated", [POIM]),
        ("q=tantareni", [POR]),
        ("q=laboratoarelor", [PEO]),
        (f"q={POCU}", [POCU]),
    ],
)
def test_projects_are_filtered(client, query, found):
    page = client.get(f"{ROOT}/projects?{query}").json()
    assert [p["smis"] for p in page["items"]] == found


def test_a_status_the_list_names_its_own_way_is_served_as_written(client):
    project = client.get(f"{ROOT}/projects/{POCU}").json()
    assert (project["status"], project["status_written"]) == (None, "etapizat")
    assert project["total"] is None
    assert project["payments"] is None and project["payments_source"] is None


def test_one_project_with_its_list_as_the_source(client):
    project = client.get(f"{ROOT}/projects/{PEO}").json()
    assert project["programme_name"] == "Programul Educație și Ocupare"
    assert (project["total"], project["eu"], project["paid"]) == (2100000.0, 1785000.0, 600000.0)
    assert (project["cofinancing_rate"], project["cut_off"]) == (0.85, "2026-09-30")
    assert project["status"] == "in_progress"
    assert project["source"]["record"] == "Lista proiectelor contractate PEO"
    assert project["source"]["sha256"] == "e1" * 32
    assert project["source"]["parser_version"] == 2


def test_the_health_programme_publishes_its_payments_one_by_one(client):
    project = client.get(f"{ROOT}/projects/{HEALTH}").json()
    assert [(p["paid_on"], p["amount"], p["kind"]) for p in project["payments"]] == [
        ("2026-09-02", 600000.0, "Plată"),
        ("2025-12-19", 300000.0, "Prefinanțare"),
    ]
    assert project["payments_source"]["documents"] == 1


def test_a_project_not_held(client):
    assert client.get(f"{ROOT}/projects/999999").status_code == 404
