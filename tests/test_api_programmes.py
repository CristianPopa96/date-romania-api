"""The Anghel Saligny endpoints, over four projects in a throwaway schema: one per match
state (see programme_seed.py)."""

import programme_seed
import pytest
from fastapi.testclient import TestClient
from programme_seed import BUILDER, DESIGNER, PARTNER, PIPES, TOWN_HALL

from date_romania.api.main import app
from date_romania.db import get_session
from date_romania.models import AwardNotice, Entity, SourceDocument

ROOT = "/v1/programmes/anghel-saligny"


@pytest.fixture
def client(session):
    doc = SourceDocument(
        source="seap-awards",
        url="https://example.test",
        sha256="a" * 64,
        storage_key="k",
        size_bytes=1,
    )
    session.add(doc)
    session.add_all(
        [
            Entity(cui=TOWN_HALL, name="Comuna Țânțăreni (Primăria Țânțăreni)", kind="authority"),
            Entity(cui=BUILDER, name="ALFA CONSTRUCT S.R.L.", kind="company"),
            Entity(cui=DESIGNER, name="Beta Birotică SRL", kind="company"),
        ]
    )
    session.flush()
    # The notice of project 101, as collected from SEAP under two ids: it was republished.
    for notice_id in (9001, 9007):
        session.add(
            AwardNotice(
                id=notice_id,
                notice_no="CAN0000001",
                buyer_cui=TOWN_HALL,
                source_document_id=doc.id,
                parser_version=2,
            )
        )
    session.flush()
    programme_seed.seed(session)
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_programme_adds_up_every_payment_file(client):
    programme = client.get(ROOT).json()
    assert (programme["payments"], programme["amount"], programme["projects"]) == (6, 7160000, 4)
    assert (programme["town_halls"], programme["builders"]) == (4, 3)
    assert (programme["first_day"], programme["last_day"]) == ("2026-05-18", "2026-08-27")
    assert [(each["key"], each["payments"], each["amount"]) for each in programme["networks"]] == [
        ("infra", 5, 6850000),
        ("gas", 1, 310000),
    ]
    # Counties by what they were paid, under their real names.
    assert [(each["key"], each["name"], each["projects"]) for each in programme["counties"]] == [
        ("GORJ", "Gorj", 2),
        ("CLUJ", "Cluj", 1),
        ("TIMIS", "Timiș", 1),
    ]
    assert programme["files"] == [
        {"published_on": "2026-05-18", "payments": 2, "amount": 2900000, "with_tax_id": 0},
        {"published_on": "2026-08-27", "payments": 4, "amount": 4260000, "with_tax_id": 4},
    ]
    assert programme["source"]["publisher"] == "data.gov.ro"
    assert programme["source"]["url"].endswith("anghel-saligny-pnias-2026-prezent")
    assert programme["contracts_source"]["url"].endswith("/achizitii-publice-2026")
    assert (programme["contracts_first_day"], programme["contracts_last_day"]) == (
        "2021-06-03",
        "2024-04-02",
    )


def test_payments_and_projects_are_counted_by_what_could_be_tied(client):
    programme = client.get(ROOT).json()
    # By payment: a payment from a file without tax IDs cannot be tied by itself.
    assert programme["payments_match"] == {
        "one": {"count": 2, "amount": 3000000},
        "several": {"count": 1, "amount": 950000},
        "none": {"count": 1, "amount": 310000},
        "unnamed": {"count": 2, "amount": 2900000},
    }
    # By project: the older payment of project 101 goes with the two that name the builder.
    assert programme["projects_match"] == {
        "one": {"count": 1, "amount": 5400000},
        "several": {"count": 1, "amount": 950000},
        "none": {"count": 1, "amount": 310000},
        "unnamed": {"count": 1, "amount": 500000},
    }
    assert (programme["method"], programme["confidence"]) == (
        "builder-cui+town-hall-name",
        "probable",
    )


def test_projects_are_listed_by_what_was_paid_and_can_be_narrowed(client):
    def ids(query: str) -> list[int]:
        page = client.get(f"{ROOT}/projects{query}").json()
        assert page["total"] == len(page["items"])
        return [project["id"] for project in page["items"]]

    assert ids("") == [101, 102, 104, 103]
    assert ids("?county=GORJ") == [101, 103]
    assert ids("?match=several") == [102]
    assert ids("?match=unnamed") == [104]
    # By the town hall or the investment, without diacritics.
    assert ids("?q=tantareni") == [101]
    assert ids("?q=canalizare") == [104]
    assert ids("?q=zzzz") == []
    assert ids(f"?builder={BUILDER}") == [101]
    page = client.get(f"{ROOT}/projects?limit=1&offset=1").json()
    assert (page["total"], [project["id"] for project in page["items"]]) == (4, [102])

    row = client.get(f"{ROOT}/projects?q=tantareni").json()["items"][0]
    assert (row["town_hall"], row["county_name"], row["network"]) == ("ȚÂNȚĂRENI", "Gorj", "infra")
    assert (row["payments"], row["paid"], row["total_value"]) == (3, 5400000, 8500000)
    assert row["match"] == "one"


def test_a_project_traced_to_one_contract(client):
    project = client.get(f"{ROOT}/projects/101").json()
    assert project["match"] == "one"
    assert (project["ministry_contract_no"], project["ministry_contract_date"]) == (
        "1872",
        "2023-05-18",
    )
    # The latest payment that gives a progress.
    assert project["progress"] == "64%"
    assert [(item["id"], item["published_on"], item["amount"]) for item in project["items"]] == [
        (30001, "2026-08-27", 1200000),
        (29001, "2026-08-27", 1800000),
        (25001, "2026-05-18", 2400000),
    ]
    # The oldest file names the builder without its tax ID: same project, same name,
    # same company.
    (builder,) = project["builders"]
    assert (builder["cui"], builder["payments"], builder["amount"]) == (BUILDER, 3, 5400000)
    assert builder["entity"]["cui"] == BUILDER
    assert builder["match"] == "one"
    (contract,) = builder["contracts"]
    assert (contract["notice_no"], contract["contract_no"]) == ("CAN0000001", "4521")
    # We also hold the notice from SEAP: the latest of its two ids.
    assert contract["notice_id"] == 9007
    assert contract["value_ron"] == 6120000
    assert contract["ratio"] == pytest.approx(0.72)
    assert contract["buyer"]["cui"] == TOWN_HALL
    # Won by two: the value is not split, and the partner we do not hold has no page.
    assert contract["partners"] == [{"cui": PARTNER, "name": "GAMA ASFALT", "entity": None}]
    # The town hall has no tax ID in the payment files; the contract's buyer gives it.
    assert project["town_hall_entity"]["cui"] == TOWN_HALL
    assert [(each["cui"], each["entity"]["name"]) for each in project["designers"]] == [
        (DESIGNER, "Beta Birotică SRL")
    ]


def test_a_project_with_several_contracts_lists_them_all(client):
    project = client.get(f"{ROOT}/projects/102").json()
    assert (project["match"], project["county_name"]) == ("several", "Cluj")
    (builder,) = project["builders"]
    assert (builder["cui"], builder["entity"], builder["match"]) == (PIPES, None, "several")
    assert [
        (contract["notice_no"], contract["title"], contract["is_framework"], contract["partners"])
        for contract in builder["contracts"]
    ] == [
        ("CAN1050001", "Modernizare DJ 109, lot 1", False, []),
        ("CAN1070002", None, True, []),
    ]
    assert builder["contracts"][0]["notice_id"] is None
    # The county council is a buyer we do not otherwise hold.
    assert project["town_hall_entity"] is None


def test_a_project_whose_chain_stops_at_the_builder(client):
    none = client.get(f"{ROOT}/projects/103").json()
    assert (none["match"], none["network"], none["poim"]) == ("none", "gas", True)
    # The builder has a contract, from another town: it is not this one's.
    assert none["builders"][0]["contracts"] == []
    assert none["designers"] == []

    unnamed = client.get(f"{ROOT}/projects/104").json()
    assert unnamed["match"] == "unnamed"
    assert unnamed["builders"] == [
        {
            "cui": None,
            "name": "Sigma Canal SRL",
            "entity": None,
            "payments": 1,
            "amount": 500000,
            "match": "unnamed",
            "contracts": [],
        }
    ]


def test_a_project_the_programme_does_not_have_is_not_found(client):
    assert client.get(f"{ROOT}/projects/999").status_code == 404
    assert client.get(f"{ROOT}/projects?match=maybe").status_code == 422
    assert client.get(f"{ROOT}/projects?q=a").status_code == 422


def test_the_programme_files_are_listed_with_the_sources(client):
    datasets = {each["key"]: each for each in client.get("/v1/datasets").json()["items"]}
    payments = datasets["pnias-payments"]
    assert (payments["first_day"], payments["last_day"]) == ("2026-05-18", "2026-08-27")
    assert payments["counts"] == {"files": 2, "rows": 6, "projects": 4}
    assert (payments["records"], payments["documents"], payments["complete"]) == (6, 2, True)
    exports = datasets["seap-exports"]
    assert exports["counts"] == {"files": 1, "rows": 5}
    assert (exports["first_day"], exports["last_day"]) == ("2021-06-03", "2024-04-02")
