"""The data endpoints, over a handful of purchases and award notices in a throwaway schema
(see conftest.py)."""

import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from date_romania.api import main
from date_romania.api.main import app
from date_romania.dates import day_bounds
from date_romania.db import get_session
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardNoticeDetail,
    AwardNoticeVersion,
    AwardWinner,
    DirectPurchase,
    Entity,
    JobRun,
    SourceDocument,
)

TOWN_HALL, HOSPITAL = 4981310, 4491342
BUILDER, STATIONER = 17886786, 18288250
# Award notices: a road with four contracts, a small services notice, a cancelled one.
ROAD, LAB, CANCELLED = 9001, 9002, 9003


def purchase(n: int, buyer: int, supplier: int | None, state: int, value: str, when: str, **more):
    return DirectPurchase(
        id=n,
        code=f"DA{n:08d}",
        name=f"Purchase {n}",
        state_id=state,
        state="Oferta acceptata" if state == 7 else "Conditii refuzate",
        cpv_code=more.pop("cpv_code", "30192000-1"),
        buyer_cui=buyer,
        buyer_text=f"{buyer} buyer",
        supplier_cui=supplier,
        supplier_text=more.pop("supplier_text", f"RO {supplier} supplier"),
        finalized_at=datetime.fromisoformat(when),
        estimated_value_ron=Decimal(value),
        closing_value=Decimal(value),
        parser_version=1,
        **more,
    )


def contract(n: int, notice: int, kind: int, value: str, when: str, winners: list, doc: int):
    """One contract and its winners; a winner is a CUI, or a text for a foreign company."""
    return [
        AwardContract(
            id=n,
            notice_id=notice,
            contract_no=str(n),
            contract_date=datetime.fromisoformat(when),
            title=f"Contract {n}",
            kind=kind,
            value=Decimal(value),
            currency="RON",
            value_ron=Decimal(value),
            source_document_id=doc,
            parser_version=2,
        ),
        *(
            AwardWinner(
                contract_id=n,
                position=position,
                supplier_cui=winner if isinstance(winner, int) else None,
                supplier_text=str(winner),
                country="Romania" if isinstance(winner, int) else "Austria",
                source_document_id=doc,
            )
            for position, winner in enumerate(winners)
        ),
    ]


def add_award_notices(session):
    """Notices collected for 5 to 7 October 2026, with contracts signed in and out of them."""
    doc = SourceDocument(
        source="seap-awards",
        url="https://example.test/a",
        sha256="a" * 64,
        storage_key="k",
        size_bytes=1,
    )
    session.add(doc)
    for day in (5, 6, 7):
        start, end = day_bounds(date(2026, 10, day))
        session.add(
            JobRun(job="seap-awards", period_start=start, period_end=end, status="succeeded")
        )
    session.flush()

    def notice(n, number, kind, buyer, title, when):
        return AwardNotice(
            id=n,
            notice_no=number,
            notice_type_id=kind,
            title=title,
            buyer_cui=buyer,
            buyer_text=f"{buyer} buyer",
            cpv_code="45233140-2",
            cpv_name="Lucrari de drumuri",
            contract_type="Lucrari",
            procedure_type="Procedura simplificata",
            published_at=datetime.fromisoformat(when),
            source_document_id=doc.id,
            parser_version=2,
        )

    session.add_all(
        [
            notice(
                ROAD,
                "CAN0000001",
                3,
                TOWN_HALL,
                "Modernizare drum comunal",
                "2026-10-06T10:00:00+03:00",
            ),
            notice(
                LAB,
                "SCNA0000002",
                18,
                HOSPITAL,
                "Analize de laborator",
                "2026-10-07T10:00:00+03:00",
            ),
            notice(
                CANCELLED,
                "CAN0000003",
                3,
                HOSPITAL,
                "Procedura anulata",
                "2026-10-07T11:00:00+03:00",
            ),
        ]
    )
    session.flush()
    rows = [
        # Won by two companies together: one value, never split.
        *contract(
            101, ROAD, 1, "6120000", "2026-10-05T12:00:00+03:00", [BUILDER, STATIONER], doc.id
        ),
        # A framework agreement: a ceiling, never counted.
        *contract(102, ROAD, 2, "1500000", "2026-10-05T12:00:00+03:00", [BUILDER], doc.id),
        *contract(103, ROAD, 3, "210000", "2026-10-06T12:00:00+03:00", [BUILDER], doc.id),
        # Signed long before the days collected: in the notice, in no period total.
        *contract(104, ROAD, 1, "900000", "2024-03-12T12:00:00+02:00", [BUILDER], doc.id),
        *contract(105, LAB, 1, "50000", "2026-10-07T12:00:00+03:00", ["ATU1 Lab GmbH"], doc.id),
    ]
    session.add_all([row for row in rows if isinstance(row, AwardContract)])
    session.flush()
    session.add_all([row for row in rows if isinstance(row, AwardWinner)])
    session.add(
        AwardNoticeDetail(
            notice_id=ROAD,
            call_notice_no="SCN0000009",
            call_published_at=datetime.fromisoformat("2024-01-10T09:00:00+02:00"),
            lots=1,
            eu_funded=True,
            financing_types=["Program / Proiect"],
            eu_funds=["Programul Regional"],
            eu_project="Proiect cod SMIS 123456",
            source_document_id=doc.id,
            parser_version=2,
        )
    )
    session.add_all(
        [
            AwardNoticeVersion(
                notice_id=ROAD,
                version_id=8000,
                state_id=10,
                state="Retras",
                published_at=datetime.fromisoformat("2024-03-20T09:00:00+02:00"),
                source_document_id=doc.id,
            ),
            AwardNoticeVersion(
                notice_id=ROAD,
                version_id=ROAD,
                state_id=2,
                state="Publicat",
                published_at=datetime.fromisoformat("2026-10-06T10:00:00+03:00"),
                source_document_id=doc.id,
            ),
        ]
    )
    session.flush()


@pytest.fixture
def client(session):
    doc = SourceDocument(
        source="seap-direct",
        url="https://example.test",
        sha256="d" * 64,
        storage_key="k",
        size_bytes=1,
    )
    session.add(doc)
    session.add_all(
        [
            Entity(cui=TOWN_HALL, name="Comuna Țânțăreni (Primăria Țânțăreni)", kind="authority"),
            Entity(cui=HOSPITAL, name="SPITALUL JUDETEAN DE URGENTA CLUJ", kind="authority"),
            Entity(cui=BUILDER, name="ALFA CONSTRUCT S.R.L.", kind="company"),
            Entity(cui=STATIONER, name="Beta Birotică SRL", kind="company"),
        ]
    )
    session.flush()
    rows = [
        purchase(1, TOWN_HALL, BUILDER, 7, "1000", "2026-10-05T10:00:00+03:00"),
        purchase(2, TOWN_HALL, BUILDER, 7, "2000", "2026-10-06T10:00:00+03:00"),
        purchase(
            3, TOWN_HALL, STATIONER, 7, "500", "2026-10-06T11:00:00+03:00", cpv_code="45233140-2"
        ),
        # Refused: it is listed, but it is not money spent.
        purchase(4, TOWN_HALL, STATIONER, 3, "9999", "2026-10-06T12:00:00+03:00"),
        # Published far above the legal limit for a direct purchase.
        purchase(5, HOSPITAL, BUILDER, 7, "5000000", "2026-10-06T13:00:00+03:00"),
        # 00:30 on 7 October in Romania, still 6 October in UTC. A foreign supplier, no CUI.
        purchase(
            6, HOSPITAL, None, 7, "700", "2026-10-06T21:30:00+00:00", supplier_text="ATU1 Lab GmbH"
        ),
    ]
    for row in rows:
        row.source_document_id = doc.id
    session.add_all(rows)
    session.flush()
    add_award_notices(session)

    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_stats_count_only_accepted_purchases_under_the_limit(client):
    stats = client.get("/v1/stats").json()
    assert stats["direct_purchases"] == {
        "purchases": 6,
        "accepted": 5,
        "value": 4200.0,
        "above_limit": 1,
        "above_limit_value": 5000000.0,
        "first_day": "2026-10-05",
        "last_day": "2026-10-07",
    }
    assert (stats["institutions"], stats["suppliers"]) == (2, 2)
    assert stats["limit"] == 900400.0
    assert stats["source"]["publisher"] == "SEAP"
    assert stats["source"]["fetched_at"] is not None


def test_institution_page_lists_its_suppliers_by_value(client):
    page = client.get(f"/v1/institutions/{TOWN_HALL}").json()
    assert page["entity"]["name"] == "Comuna Țânțăreni (Primăria Țânțăreni)"
    assert page["direct_purchases"]["purchases"] == 4
    assert page["direct_purchases"]["accepted"] == 3
    assert page["direct_purchases"]["value"] == 3500.0
    assert [(p["cui"], p["accepted"], p["value"]) for p in page["partners"]] == [
        (BUILDER, 2, 3000.0),
        (STATIONER, 1, 500.0),
    ]


def test_supplier_page_keeps_a_value_above_the_limit_apart(client):
    page = client.get(f"/v1/suppliers/{BUILDER}").json()
    assert page["direct_purchases"]["value"] == 3000.0
    assert page["direct_purchases"]["above_limit"] == 1
    assert page["direct_purchases"]["above_limit_value"] == 5000000.0
    assert [p["cui"] for p in page["partners"]] == [TOWN_HALL]


def test_unknown_cui_and_purchase_are_not_found(client):
    assert client.get("/v1/institutions/361684").status_code == 404
    assert client.get("/v1/suppliers/361684").status_code == 404
    assert client.get("/v1/direct-purchases/999").status_code == 404


def test_direct_purchases_can_be_filtered_sorted_and_paged(client):
    def ids(**params):
        page = client.get("/v1/direct-purchases", params=params).json()
        return page["total"], [item["id"] for item in page["items"]]

    assert ids() == (6, [6, 5, 4, 3, 2, 1])
    assert ids(sort="value") == (6, [5, 4, 2, 1, 6, 3])
    assert ids(buyer=TOWN_HALL, state=7) == (3, [3, 2, 1])
    assert ids(supplier=STATIONER) == (2, [4, 3])
    assert ids(cpv="4523") == (1, [3])
    assert ids(limit=2, offset=4) == (6, [2, 1])
    # Days are Romanian days: purchase 6 belongs to 7 October.
    assert ids(date_from="2026-10-07", date_to="2026-10-07") == (1, [6])
    assert ids(date_from="2026-10-06", date_to="2026-10-06") == (4, [5, 4, 3, 2])
    assert client.get("/v1/direct-purchases", params={"limit": 101}).status_code == 422


def test_direct_purchase_carries_its_parties_and_its_source(client):
    row = client.get("/v1/direct-purchases/5").json()
    assert row["buyer"] == {
        "cui": HOSPITAL,
        "name": "SPITALUL JUDETEAN DE URGENTA CLUJ",
        "kind": "authority",
    }
    assert row["supplier"]["cui"] == BUILDER
    assert (row["value"], row["above_limit"]) == (5000000.0, True)
    assert row["source"]["publisher"] == "SEAP"
    assert row["source"]["record"] == "DA00000005"
    assert row["source"]["url"].endswith("/5")
    assert row["source"]["document_id"] is not None

    foreign = client.get("/v1/direct-purchases/6").json()
    assert foreign["supplier"] is None
    assert foreign["supplier_text"] == "ATU1 Lab GmbH"
    assert foreign["above_limit"] is False


def test_a_refused_purchase_is_never_above_the_limit(client, session):
    refused = session.get(DirectPurchase, 4)
    refused.closing_value = 250_000_000
    session.flush()
    row = client.get("/v1/direct-purchases/4").json()
    assert (row["state_id"], row["value"], row["above_limit"]) == (3, 250000000.0, False)


def test_rankings_order_by_accepted_value(client):
    suppliers = client.get("/v1/rankings/suppliers").json()
    assert [(r["rank"], r["cui"], r["value"]) for r in suppliers["items"]] == [
        (1, BUILDER, 3000.0),
        (2, STATIONER, 500.0),
    ]
    institutions = client.get("/v1/rankings/institutions").json()
    assert [(r["cui"], r["value"]) for r in institutions["items"]] == [
        (TOWN_HALL, 3500.0),
        (HOSPITAL, 700.0),
    ]
    one_day = client.get(
        "/v1/rankings/suppliers", params={"date_from": "2026-10-05", "date_to": "2026-10-05"}
    ).json()
    assert [(r["cui"], r["value"]) for r in one_day["items"]] == [(BUILDER, 1000.0)]
    assert one_day["date_from"] == "2026-10-05"


def test_search_forgives_diacritics_word_order_and_typos(client):
    def found(q, **params):
        items = client.get("/v1/search", params={"q": q, **params}).json()["items"]
        return [item["cui"] for item in items]

    assert found("tantareni") == [TOWN_HALL]
    assert found("ȚÂNȚĂRENI primaria") == [TOWN_HALL]
    assert found("cluj spital") == [HOSPITAL]
    assert found("alfa constrct") == [BUILDER]
    assert found("birotica") == [STATIONER]
    assert found("nothing like this") == []
    # A percent sign is text, not a wildcard.
    assert found("%%") == []


def test_search_by_cui_and_by_kind(client):
    def found(q, **params):
        items = client.get("/v1/search", params={"q": q, **params}).json()["items"]
        return [item["cui"] for item in items]

    assert found("RO 17886786") == [BUILDER]
    assert found("1788") == [BUILDER]
    assert found("44") == [HOSPITAL]
    assert found("44", kind="company") == []
    assert client.get("/v1/search", params={"q": "a"}).status_code == 422


# The calls the site makes for the pages its browser tests open. Their answers are kept in
# a file that the site's stub API serves, so those tests run on what this API really says.
SITE_STUB = Path(__file__).parent / "fixtures" / "site_stub.json"


def test_a_notice_totals_its_own_contracts_whatever_their_date(client):
    notice = client.get(f"/v1/award-notices/{ROAD}").json()

    assert (notice["notice_no"], notice["buyer"]["cui"]) == ("CAN0000001", TOWN_HALL)
    assert (
        notice["contracts"],
        notice["ordinary"],
        notice["frameworks"],
        notice["subsequent"],
    ) == (
        4,
        1 + 1,
        1,
        1,
    )
    # The framework agreement is left out; the contract from 2024 is in.
    assert notice["total"] == 6120000 + 210000 + 900000
    assert notice["first_published_at"].startswith("2024-03-20")
    assert notice["published_at"].startswith("2026-10-06")
    assert notice["versions"] == 2
    assert notice["detail"]["eu_funded"] is True
    assert notice["detail"]["call_notice_no"] == "SCN0000009"
    assert notice["source"]["record"] == "CAN0000001"
    assert notice["source"]["url"].endswith(f"/view-c/{ROAD}")


def test_a_notice_not_yet_read_in_detail_says_so_with_nulls(client):
    notice = client.get(f"/v1/award-notices/{LAB}").json()
    assert (notice["detail"], notice["versions"], notice["first_published_at"]) == (
        None,
        None,
        None,
    )
    # Only notices of type 3 have a public page we have checked.
    assert notice["source"]["url"].endswith("/contract-award-notices/list/0/0")

    empty = client.get(f"/v1/award-notices/{CANCELLED}").json()
    assert (empty["contracts"], empty["total"]) == (0, 0)
    assert client.get(f"/v1/award-notices/{CANCELLED}/contracts").json()["items"] == []
    assert client.get("/v1/award-notices/9999").status_code == 404
    assert client.get("/v1/award-notices/9999/contracts").status_code == 404


def test_the_contracts_of_a_notice_keep_the_association_whole(client):
    page = client.get(f"/v1/award-notices/{ROAD}/contracts").json()

    assert (page["total"], page["period"]) == (4, None)
    assert [row["id"] for row in page["items"]] == [104, 101, 102, 103]
    by_id = {row["id"]: row for row in page["items"]}
    together = by_id[101]
    assert [winner["supplier"]["cui"] for winner in together["winners"]] == [BUILDER, STATIONER]
    assert together["value"] == 6120000
    assert (by_id[102]["kind"], by_id[102]["counted"]) == (2, False)
    assert all(by_id[n]["counted"] for n in (101, 103, 104))

    foreign = client.get(f"/v1/award-notices/{LAB}/contracts").json()["items"][0]["winners"][0]
    assert (foreign["supplier"], foreign["text"], foreign["country"]) == (
        None,
        "ATU1 Lab GmbH",
        "Austria",
    )


def test_contract_lists_count_only_what_was_signed_in_the_period(client):
    page = client.get(f"/v1/award-contracts?buyer={TOWN_HALL}").json()
    assert page["period"] == {"first_day": "2026-10-05", "last_day": "2026-10-07"}
    # Not the framework agreement, not the contract from 2024.
    assert [row["id"] for row in page["items"]] == [103, 101]

    largest = client.get("/v1/award-contracts?sort=value&limit=2").json()
    assert (largest["total"], [row["id"] for row in largest["items"]]) == (3, [101, 103])

    won_alone = client.get(f"/v1/award-contracts?supplier={BUILDER}&won=alone").json()
    assert [row["id"] for row in won_alone["items"]] == [103]
    together = client.get(f"/v1/award-contracts?supplier={STATIONER}&won=association").json()
    assert [row["id"] for row in together["items"]] == [101]


def test_a_supplier_has_two_figures_that_are_never_added(client):
    builder = client.get(f"/v1/suppliers/{BUILDER}/contracts").json()
    assert builder["alone"] == {"contracts": 1, "value": 210000}
    assert builder["association"] == {"contracts": 1, "value": 6120000}

    partner = client.get(f"/v1/suppliers/{STATIONER}/contracts").json()
    assert partner["alone"] == {"contracts": 0, "value": 0}
    # The whole value again: SEAP does not say how the two shared it.
    assert partner["association"] == {"contracts": 1, "value": 6120000}


def test_an_institution_counts_each_contract_once(client):
    town_hall = client.get(f"/v1/institutions/{TOWN_HALL}/contracts").json()
    assert (town_hall["contracts"], town_hall["value"]) == (2, 6120000 + 210000)
    assert town_hall["period"]["last_day"] == "2026-10-07"
    assert client.get("/v1/institutions/12345674/contracts").status_code == 404


def test_contract_rankings_keep_alone_and_association_apart(client):
    alone = client.get("/v1/rankings/contract-suppliers").json()
    assert alone["won"] == "alone"
    assert [(row["cui"], row["value"]) for row in alone["items"]] == [(BUILDER, 210000)]

    together = client.get("/v1/rankings/contract-suppliers?won=association").json()
    assert [(row["rank"], row["cui"], row["value"]) for row in together["items"]] == [
        (1, BUILDER, 6120000),
        (2, STATIONER, 6120000),
    ]

    buyers = client.get("/v1/rankings/contract-institutions").json()
    assert [(row["cui"], row["contracts"], row["value"]) for row in buyers["items"]] == [
        (TOWN_HALL, 2, 6330000),
        (HOSPITAL, 1, 50000),
    ]


def test_without_a_collected_day_no_contract_is_counted(client, session):
    session.execute(JobRun.__table__.delete())
    page = client.get(f"/v1/award-contracts?buyer={TOWN_HALL}").json()
    assert (page["total"], page["period"]) == (0, {"first_day": None, "last_day": None})


def test_contracts_as_a_file_name_their_source_on_every_row(client):
    response = client.get(f"/v1/award-contracts?buyer={TOWN_HALL}&sort=value&format=csv")

    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "contracte.csv" in response.headers["content-disposition"]
    lines = response.text.lstrip("\ufeff").splitlines()
    assert lines[0].startswith("notice_no,contract_no,signed_at,kind,title,buyer_cui")
    assert len(lines) == 1 + 2
    assert lines[1].startswith("CAN0000001,101,2026-10-05")
    assert f"{BUILDER}; {STATIONER}" in lines[1]
    assert "ALFA CONSTRUCT S.R.L.; Beta Birotică SRL" in lines[1]
    assert ",6120000.0,SEAP,https://e-licitatie.ro/" in lines[1]


def test_datasets_say_what_the_site_is_built_on(client):
    direct, awards = client.get("/v1/datasets").json()["items"]
    assert (direct["key"], direct["records"], direct["complete"]) == ("seap-direct", 6, True)
    assert (direct["first_day"], direct["last_day"]) == ("2026-10-05", "2026-10-07")
    # The three contracts the totals count, not every contract held.
    assert (awards["key"], awards["records"], awards["complete"]) == ("seap-awards", 3, False)
    assert (awards["first_day"], awards["last_day"]) == ("2026-10-05", "2026-10-07")


def test_a_buyer_and_a_supplier_have_a_summary_together(client):
    pair = client.get(f"/v1/direct-purchases/summary?buyer={TOWN_HALL}&supplier={BUILDER}").json()
    assert (pair["purchases"], pair["accepted"], pair["value"]) == (2, 2, 3000)
    # A refused offer is counted as a purchase, never as money.
    other = client.get(
        f"/v1/direct-purchases/summary?buyer={TOWN_HALL}&supplier={STATIONER}"
    ).json()
    assert (other["purchases"], other["accepted"], other["value"]) == (2, 1, 500)


SITE_CALLS = (
    "/v1/health",
    "/v1/stats",
    "/v1/search?q=tantareni&limit=30",
    "/v1/search?q=zzzz&limit=30",
    # A CUI typed in the search box: one that buys, one that sells, one we do not hold.
    f"/v1/search?q={TOWN_HALL}&limit=30",
    f"/v1/search?q={BUILDER}&limit=30",
    "/v1/search?q=12345674&limit=30",
    f"/v1/institutions/{TOWN_HALL}?partners=10",
    f"/v1/direct-purchases?buyer={TOWN_HALL}&sort=newest&limit=20&offset=0",
    f"/v1/direct-purchases?buyer={TOWN_HALL}&sort=value&state=7&limit=20&offset=0",
    f"/v1/suppliers/{BUILDER}?partners=10",
    f"/v1/direct-purchases?supplier={BUILDER}&sort=newest&limit=20&offset=0",
    "/v1/institutions/12345674?partners=10",
    "/v1/direct-purchases?buyer=12345674&sort=newest&limit=20&offset=0",
    "/v1/rankings/suppliers?limit=20",
    "/v1/rankings/institutions?limit=20",
    "/v1/datasets",
    f"/v1/award-notices/{ROAD}",
    f"/v1/award-notices/{ROAD}/contracts?limit=50&offset=0",
    f"/v1/award-notices/{LAB}",
    f"/v1/award-notices/{LAB}/contracts?limit=50&offset=0",
    f"/v1/award-notices/{CANCELLED}",
    f"/v1/award-notices/{CANCELLED}/contracts?limit=50&offset=0",
    "/v1/award-notices/9999",
    "/v1/direct-purchases/3",
    "/v1/direct-purchases/4",
    "/v1/direct-purchases/5",
    "/v1/direct-purchases/999",
    f"/v1/direct-purchases/summary?buyer={TOWN_HALL}&supplier={STATIONER}",
    f"/v1/direct-purchases/summary?buyer={HOSPITAL}&supplier={BUILDER}",
    f"/v1/institutions/{TOWN_HALL}/contracts",
    f"/v1/award-contracts?buyer={TOWN_HALL}&sort=newest&limit=20&offset=0",
    f"/v1/suppliers/{BUILDER}/contracts",
    f"/v1/award-contracts?supplier={BUILDER}&sort=newest&limit=20&offset=0",
    "/v1/institutions/12345674/contracts",
    "/v1/award-contracts?sort=value&limit=20&offset=0",
    "/v1/rankings/contract-suppliers?won=alone&limit=20",
    "/v1/rankings/contract-suppliers?won=association&limit=20",
    "/v1/rankings/contract-institutions?limit=20",
)


def _steady(value):
    """The same answer on every run: the time a file was fetched is the time of the test."""
    if isinstance(value, dict):
        return {
            key: "2026-10-07T04:30:00Z" if key == "fetched_at" and item else _steady(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_steady(item) for item in value]
    return value


def test_the_site_stub_holds_what_the_api_answers(client, monkeypatch):
    """Fails when an answer the site depends on changes.

    Then run `WRITE_SITE_STUB=1 uv run pytest tests/test_api_data.py`, and copy the file to
    `e2e/stub/answers.json` in date-romania-web, where the browser tests will show what the
    change does to the pages.
    """
    monkeypatch.setattr(main, "database_ok", lambda: True)
    answers = {}
    for call in SITE_CALLS:
        response = client.get(call)
        answers[call] = {"status": response.status_code, "body": _steady(response.json())}
    text = json.dumps(answers, ensure_ascii=False, indent=1) + "\n"
    if os.environ.get("WRITE_SITE_STUB"):
        SITE_STUB.write_bytes(text.encode("utf-8"))
    assert SITE_STUB.read_text(encoding="utf-8") == text
