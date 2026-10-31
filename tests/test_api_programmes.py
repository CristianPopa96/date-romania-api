"""The Anghel Saligny endpoints, over four projects in a throwaway schema: one per match
state (see programme_seed.py)."""

import programme_seed
import pytest
from fastapi.testclient import TestClient
from programme_seed import BUILDER, DESIGNER, PARTNER, PIPES, TOWN_HALL

from date_romania import pnias_links
from date_romania.api.main import app
from date_romania.db import get_session
from date_romania.models import (
    AwardNotice,
    Entity,
    ExportBuyer,
    ExportContract,
    PniasLink,
    SourceDocument,
)

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
    # By payment: a payment from a file without tax IDs is tied through a newer payment
    # of its project that names the same builder with one (project 101); alone, it cannot
    # be (project 104).
    assert programme["payments_match"] == {
        "one": {"count": 3, "amount": 5400000},
        "several": {"count": 1, "amount": 950000},
        "none": {"count": 1, "amount": 310000},
        "unnamed": {"count": 1, "amount": 500000},
    }
    # By project: the older payment of project 101 goes with the two that name the builder.
    assert programme["projects_match"] == {
        "one": {"count": 1, "amount": 5400000},
        "several": {"count": 1, "amount": 950000},
        "none": {"count": 1, "amount": 310000},
        "unnamed": {"count": 1, "amount": 500000},
    }
    # The payment of the county of Cluj is tied to a buyer whose name two buyers carry.
    # It has two possible contracts, so it is counted under `several`.
    nothing = {"count": 0, "amount": 0}
    assert programme["payments_possible"] == {
        "one": nothing,
        "several": {"count": 1, "amount": 950000},
        "none": nothing,
        "unnamed": nothing,
    }


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

    # In any column's order, and by several states at once.
    assert ids("?sort=paid&order=asc") == [103, 104, 102, 101]
    assert ids("?match=several&match=unnamed") == [102, 104]


def test_the_projects_say_what_their_filters_keep(client):
    def overview(query: str = "") -> dict:
        return client.get(f"{ROOT}/projects/overview{query}").json()

    whole = overview()
    assert whole["summary"] == {"projects": 4, "payments": 6, "paid": 7_160_000}
    assert whole["whole"] == 4
    assert [(c["value"], c["name"], c["count"], c["paid"]) for c in whole["counties"]] == [
        ("GORJ", "Gorj", 2, 5_710_000),
        ("CLUJ", "Cluj", 1, 950_000),
        ("TIMIS", "Timiș", 1, 500_000),
    ]
    assert {m["value"]: m["count"] for m in whole["matches"]} == {
        "none": 1,
        "one": 1,
        "several": 1,
        "unnamed": 1,
    }
    assert whole["categories"][0] == {"value": "Drumurile publice", "count": 2}
    # The programme names the same kinds of works, for an address to name one.
    assert client.get(ROOT).json()["categories"] == [c["value"] for c in whole["categories"]]

    # A builder named: its entity, and each option counted under the other filters.
    built = overview(f"?county=GORJ&builder={BUILDER}")
    assert built["summary"] == {"projects": 1, "payments": 3, "paid": 5_400_000}
    assert built["builder"]["cui"] == BUILDER
    assert built["counties"] == [{"value": "GORJ", "name": "Gorj", "count": 1, "paid": 5_400_000}]

    empty = overview("?county=GORJ&match=several")
    assert empty["summary"]["projects"] == 0
    assert empty["without"] == [
        {"param": "county", "count": 1},
        {"param": "match", "count": 2},
    ]


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
    # An export puts the buyer in the project's county.
    assert (contract["confidence"], contract["method"]) == (
        "probable",
        "builder-cui+town-hall-name+county",
    )
    assert project["confidence"] == "probable"
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
    # Two buyers are named like the county, and nothing says which is which.
    assert {contract["confidence"] for contract in builder["contracts"]} == {"possible"}
    assert project["confidence"] == "possible"
    # The county council is a buyer we do not otherwise hold.
    assert project["town_hall_entity"] is None


def test_a_project_whose_chain_stops_at_the_builder(client):
    none = client.get(f"{ROOT}/projects/103").json()
    assert (none["match"], none["network"], none["poim"]) == ("none", "gas", True)
    # The builder has a contract, from another town: it is not this one's.
    assert none["builders"][0]["contracts"] == []
    assert none["designers"] == []
    assert none["confidence"] is None

    unnamed = client.get(f"{ROOT}/projects/104").json()
    assert unnamed["match"] == "unnamed"
    assert unnamed["builders"] == [
        {
            "cui": None,
            "name": "Sigma Canal SRL",
            "entity": None,
            "found_by": None,
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


def test_a_contract_without_its_number_still_shows(client, session):
    # An export can leave the contract number empty; the page must not fail on it.
    for contract in session.query(ExportContract).filter_by(notice_no="CAN0000001"):
        contract.contract_no = None
    session.flush()
    pnias_links.link(session)
    project = client.get(f"{ROOT}/projects/101").json()
    (contract,) = project["builders"][0]["contracts"]
    assert contract["contract_no"] is None
    assert [partner["name"] for partner in contract["partners"]] == ["GAMA ASFALT"]


def test_a_buyer_from_another_county_is_not_the_town_hall(client, session):
    # The same name, and an export that puts this buyer elsewhere: no link.
    session.get(ExportBuyer, TOWN_HALL).county = "DOLJ"
    session.flush()
    pnias_links.link(session)
    project = client.get(f"{ROOT}/projects/101").json()
    assert project["match"] == "none"
    assert project["builders"][0]["contracts"] == []


def test_a_name_no_other_buyer_carries_is_enough(client, session):
    # No export says where the buyer is, and it is the only one of that name.
    session.get(ExportBuyer, TOWN_HALL).county = None
    session.flush()
    pnias_links.link(session)
    methods = set(session.query(PniasLink.method).filter(PniasLink.payment_id == 30001))
    assert methods == {("builder-cui+only-town-hall-of-that-name",)}
    assert client.get(f"{ROOT}/projects/101").json()["confidence"] == "probable"


def test_only_works_contracts_are_tied(client, session):
    # The same builder clears the snow for the same town hall: not what a payment settles.
    for contract in session.query(ExportContract).filter_by(notice_no="CAN0000001"):
        contract.contract_type, contract.cpv_code = "Servicii", "90620000-9"
    session.flush()
    pnias_links.link(session)
    assert client.get(f"{ROOT}/projects/101").json()["match"] == "none"


def test_search_words_are_not_wildcards(client):
    assert client.get(f"{ROOT}/projects?q=%25%25").json()["total"] == 0
    assert client.get(f"{ROOT}/projects?q=__").json()["total"] == 0


def test_a_namesake_written_with_its_county_still_makes_the_name_shared(client, session):
    # No export says where the town hall is. Another buyer is a Țânțăreni too, written
    # with its own county after the name: the link is possible, not probable.
    session.get(ExportBuyer, TOWN_HALL).county = None
    session.add(ExportBuyer(cui=30000055, name="COMUNA TANTARENI DOLJ", source_document_id=1))
    session.flush()
    pnias_links.link(session)
    methods = set(session.query(PniasLink.method).filter(PniasLink.payment_id == 30001))
    assert methods == {("builder-cui+town-hall-name",)}
    programme = client.get(ROOT).json()
    assert programme["payments_possible"]["one"] == {"count": 3, "amount": 5400000}
    assert client.get(f"{ROOT}/projects/101").json()["confidence"] == "possible"
