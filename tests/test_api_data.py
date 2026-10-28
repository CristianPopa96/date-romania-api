"""The data endpoints, over a handful of purchases and award notices in a throwaway schema
(see conftest.py)."""

import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import eu_seed
import places_seed
import pnrr_seed
import programme_seed
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from date_romania import eu_seap_links
from date_romania.api import main
from date_romania.api.main import app
from date_romania.collectors.jobs import record_skipped
from date_romania.dates import day_bounds
from date_romania.db import get_session
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardNoticeDetail,
    AwardNoticeVersion,
    AwardWinner,
    DirectPurchase,
    DirectPurchaseDetail,
    DirectPurchaseItem,
    Entity,
    JobRun,
    PnrrPayment,
    Report,
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


def add_purchase_detail(session):
    """The lines and conditions of purchase 3, read from its own page, one of them turned
    down by the supplier; the others have none."""
    doc = SourceDocument(
        source="seap-direct-details",
        url="https://e-licitatie.ro/api-pub/PublicDirectAcquisition/getView/3",
        sha256="d3" * 32,
        storage_key="k3",
        size_bytes=1,
        parser_version=1,
        rejected_rows=0,
    )
    session.add(doc)
    session.flush()
    session.add(
        DirectPurchaseDetail(
            purchase_id=3,
            # Its PNRR contract, cited by number: the purchase is tied to it.
            description="Rechizite pentru primărie, contract de finanțare nr. 12321/26.08.2024",
            payment_condition="OP la 30 de zile de la recepție",
            delivery_condition="La sediul primăriei",
            eu_funded=False,
            source_document_id=doc.id,
            parser_version=1,
        )
    )
    session.flush()
    session.add_all(
        [
            DirectPurchaseItem(
                purchase_id=3,
                position=position,
                name=name,
                cpv_code="30192000-1",
                quantity=Decimal(quantity),
                unit=unit,
                unit_price=Decimal(price),
                rejected=rejected,
                source_document_id=doc.id,
            )
            for position, (name, quantity, unit, price, rejected) in enumerate(
                [
                    ("Hârtie copiator A4", "10", "top", "25", False),
                    ("Toner imprimantă", "2", "bucată", "125", False),
                    ("Plicuri C4", "100", "bucată", "1.5", True),
                ],
                1,
            )
        ]
    )


def add_award_notices(session):
    """Notices collected for 5 to 7 October 2026, with contracts signed in and out of them."""
    doc = SourceDocument(
        source="seap-awards",
        url="https://example.test/a",
        sha256="a" * 64,
        storage_key="k",
        size_bytes=1,
        parser_version=2,
        rejected_rows=2,
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
            # The town hall's POR project: the notice is tied to it.
            eu_project="Proiect cod SMIS 118001",
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
        parser_version=3,
        rejected_rows=0,
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
    add_purchase_detail(session)
    add_award_notices(session)
    # Reports from readers: one checked and corrected, one still waiting, one turned down.
    session.add_all(
        [
            Report(
                page=f"/contracte/{ROAD}",
                message="Valoarea contractului 2 include TVA.",
                status="accepted",
                correction="Valoarea contractului 2 era cu TVA; acum e fără TVA, ca în SEAP.",
                reviewed_at=datetime.fromisoformat("2026-10-08T10:00:00+03:00"),
            ),
            Report(page=f"/institutii/{TOWN_HALL}", message="Numele e scris greșit.", status="new"),
            Report(page="/surse", message="Nu sunt de acord cu cifrele.", status="rejected"),
        ]
    )
    session.flush()
    programme_seed.seed(session)
    places_seed.seed(session)
    pnrr_seed.seed(session)
    eu_seed.seed(session)
    eu_seap_links.link(session)

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
    # One record: the hash of the stored response and the parser that read it.
    assert (row["source"]["sha256"], row["source"]["parser_version"]) == ("d" * 64, 1)

    foreign = client.get("/v1/direct-purchases/6").json()
    assert foreign["supplier"] is None
    assert foreign["supplier_text"] == "ATU1 Lab GmbH"
    assert foreign["above_limit"] is False


def test_one_purchase_carries_its_lines_once_collected(client):
    detail = client.get("/v1/direct-purchases/3").json()["detail"]
    assert (detail["payment_condition"], detail["delivery_condition"]) == (
        "OP la 30 de zile de la recepție",
        "La sediul primăriei",
    )
    assert [
        (i["name"], i["quantity"], i["unit"], i["unit_price"], i["value"]) for i in detail["items"]
    ] == [
        ("Hârtie copiator A4", 10.0, "top", 25.0, 250.0),
        ("Toner imprimantă", 2.0, "bucată", 125.0, 250.0),
        ("Plicuri C4", 100.0, "bucată", 1.5, 150.0),
    ]
    # The total is what was bought: not the line the supplier turned down.
    assert [i["rejected"] for i in detail["items"]] == [False, False, True]
    assert detail["items_value"] == 500.0
    # Its own source: the stored answer of the purchase's page.
    assert (detail["source"]["sha256"], detail["source"]["parser_version"]) == ("d3" * 32, 1)
    assert detail["source"]["url"].endswith("/view/3")
    # Not collected yet: no lines, rather than an empty list.
    assert client.get("/v1/direct-purchases/5").json()["detail"] is None
    # The lists never carry it.
    assert "detail" not in client.get("/v1/direct-purchases").json()["items"][0]


def test_a_purchase_page_with_no_lines_has_no_total(client, session):
    session.execute(delete(DirectPurchaseItem))
    session.flush()
    detail = client.get("/v1/direct-purchases/3").json()["detail"]
    assert (detail["items"], detail["items_value"]) == ([], None)


def test_a_refused_purchase_is_never_above_the_limit(client, session):
    refused = session.get(DirectPurchase, 4)
    refused.closing_value = 250_000_000
    session.flush()
    row = client.get("/v1/direct-purchases/4").json()
    assert (row["state_id"], row["value"], row["above_limit"]) == (3, 250000000.0, False)


def test_a_purchase_is_held_to_the_limit_of_its_type_and_annex_2_to_none(client, session):
    """Goods and services stop at 270,120 lei, works at 900,400; Annex 2 services, told by
    CPV code whatever their type, have no limit (Crispy, 22.10.2026)."""
    before = client.get("/v1/stats").json()["direct_purchases"]
    doc = session.scalar(select(SourceDocument.id).where(SourceDocument.source == "seap-direct"))
    rows = [
        # Goods above their own limit, under the works one: set apart.
        purchase(30, HOSPITAL, STATIONER, 7, "300000", "2026-10-06T14:00:00+03:00"),
        # Works at the same value: under their limit.
        purchase(31, TOWN_HALL, BUILDER, 7, "300000", "2026-10-06T15:00:00+03:00"),
        # Hospital catering (Annex 2), filed as goods, above both limits: counted.
        purchase(
            32,
            HOSPITAL,
            STATIONER,
            7,
            "1000000",
            "2026-10-06T16:00:00+03:00",
            cpv_code="55520000-1",
        ),
        # Near the goods limit, but an Annex 2 service twice: no pattern.
        purchase(
            33, HOSPITAL, BUILDER, 7, "260000", "2026-10-05T16:00:00+03:00", cpv_code="85100000-0"
        ),
        purchase(
            34, HOSPITAL, BUILDER, 7, "265000", "2026-10-06T16:00:00+03:00", cpv_code="85100000-0"
        ),
    ]
    kinds = {30: GOODS, 31: WORKS, 32: GOODS, 33: SERVICES, 34: SERVICES}
    for row in rows:
        row.source_document_id = doc
        row.contract_type_id = kinds[row.id]
    session.add_all(rows)
    session.flush()

    summary = client.get("/v1/stats").json()["direct_purchases"]
    assert summary["above_limit"] == before["above_limit"] + 1
    assert summary["above_limit_value"] == before["above_limit_value"] + 300000
    assert summary["value"] == before["value"] + 300000 + 1000000 + 260000 + 265000
    goods = client.get("/v1/direct-purchases/30").json()
    assert (goods["contract_type_id"], goods["limit"], goods["above_limit"]) == (
        GOODS,
        270120.0,
        True,
    )
    assert client.get("/v1/direct-purchases/31").json()["above_limit"] is False
    catering = client.get("/v1/direct-purchases/32").json()
    assert (catering["limit"], catering["above_limit"]) == (None, False)
    # A purchase whose type is not known is held to the highest limit.
    assert client.get("/v1/direct-purchases/1").json()["limit"] == 900400.0

    pattern = client.get("/v1/patterns/near-limit").json()
    assert pattern["pairs"] == 0
    assert pattern["annex_2"] == 3
    assert (
        pattern["checked"] + pattern["unknown_type"] + pattern["annex_2"]
        == (pattern["accepted_total"])
    )


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
OPENAPI = Path(__file__).parent / "fixtures" / "openapi.json"


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
    assert notice["source"]["sha256"] == "a" * 64

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


def test_a_withdrawn_notice_does_not_count_its_contracts_again(client, session):
    """SEAP published the road notice before under another id, and we hold that one too."""
    before = client.get(f"/v1/institutions/{TOWN_HALL}/contracts").json()
    doc = session.scalar(select(SourceDocument.id).where(SourceDocument.source == "seap-awards"))
    session.add(
        AwardNotice(
            id=8000,
            notice_no="CAN0000001",
            notice_type_id=3,
            title="Modernizare drum comunal",
            buyer_cui=TOWN_HALL,
            published_at=datetime.fromisoformat("2026-10-05T10:00:00+03:00"),
            source_document_id=doc,
            parser_version=2,
        )
    )
    session.flush()
    rows = contract(203, 8000, 3, "210000", "2026-10-06T12:00:00+03:00", [BUILDER], doc)
    session.add(rows[0])
    session.flush()
    session.add_all(rows[1:])
    session.flush()
    # SEAP lists every version under each of them, the newer one too.
    session.add_all(
        AwardNoticeVersion(notice_id=8000, version_id=version, state_id=2, source_document_id=doc)
        for version in (8000, ROAD)
    )
    session.flush()

    assert client.get(f"/v1/institutions/{TOWN_HALL}/contracts").json() == before
    assert before["contracts"] == 2
    page = client.get(f"/v1/award-contracts?buyer={TOWN_HALL}").json()
    assert [row["id"] for row in page["items"]] == [103, 101]
    builder = client.get(f"/v1/suppliers/{BUILDER}/contracts").json()
    assert builder["alone"] == {"contracts": 1, "value": 210000}
    alone = client.get("/v1/rankings/contract-suppliers").json()
    assert [(row["cui"], row["contracts"]) for row in alone["items"]] == [(BUILDER, 1)]
    assert client.get("/v1/datasets").json()["items"][1]["records"] == 3
    # The withdrawn notice keeps its own page, with its own contracts, and names the one
    # that replaced it.
    withdrawn = client.get("/v1/award-notices/8000").json()
    assert (withdrawn["contracts"], withdrawn["replaced_by"]) == (1, ROAD)
    assert client.get(f"/v1/award-notices/{ROAD}").json()["replaced_by"] is None


def test_a_day_collected_far_from_the_rest_does_not_stretch_the_period(client, session):
    start, end = day_bounds(date(2025, 1, 15))
    session.add(JobRun(job="seap-awards", period_start=start, period_end=end, status="succeeded"))
    session.flush()

    page = client.get(f"/v1/award-contracts?buyer={TOWN_HALL}").json()
    assert page["period"] == {"first_day": "2026-10-05", "last_day": "2026-10-07"}


def test_a_company_listed_twice_in_a_contract_is_one_winner(client, session):
    """SEAP can repeat a winner; the contract is not an association and counts once."""
    doc = session.scalar(select(SourceDocument.id).where(SourceDocument.source == "seap-awards"))
    rows = contract(106, LAB, 1, "40000", "2026-10-07T12:00:00+03:00", [STATIONER, STATIONER], doc)
    session.add(rows[0])
    session.flush()
    session.add_all(rows[1:])
    session.flush()

    stationer = client.get(f"/v1/suppliers/{STATIONER}/contracts").json()
    assert stationer["alone"] == {"contracts": 1, "value": 40000}
    alone = client.get("/v1/rankings/contract-suppliers").json()
    assert [(row["cui"], row["contracts"], row["value"]) for row in alone["items"]] == [
        (BUILDER, 1, 210000),
        (STATIONER, 1, 40000),
    ]


def test_a_file_cell_that_starts_like_a_formula_is_quoted(client, session):
    session.get(AwardContract, 103).title = "=1+1"
    session.flush()

    lines = client.get(f"/v1/award-contracts?buyer={TOWN_HALL}&format=csv").text.splitlines()
    assert ",3,'=1+1," in lines[1]


def test_the_file_holds_the_whole_list_past_one_batch(client, monkeypatch):
    monkeypatch.setattr("date_romania.api.routes.awards.CSV_BATCH", 1)
    lines = client.get("/v1/award-contracts?sort=value&format=csv").text.splitlines()
    assert [line.split(",")[1] for line in lines[1:]] == ["101", "103", "105"]


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
    # The two sources read by day come first; the ones that come as files follow.
    direct, awards, *files = client.get("/v1/datasets").json()["items"]
    # The places seed holds a budget file, so its source is listed; the others are not
    # held here, and a source is listed only once a file of it is.
    assert [each["key"] for each in files] == ["pnias-payments", "seap-exports", "local-budgets"]
    budgets = files[2]
    assert (budgets["first_day"], budgets["last_day"], budgets["records"]) == (
        "2024-01-01",
        "2024-12-31",
        1,
    )
    assert budgets["counts"] == {"files": 1, "rows": 1, "figures": 12, "population": 1}
    assert (direct["key"], direct["records"], direct["complete"]) == ("seap-direct", 6, True)
    assert (direct["first_day"], direct["last_day"]) == ("2026-10-05", "2026-10-07")
    # The three contracts the totals count, not every contract held.
    assert (awards["key"], awards["records"], awards["complete"]) == ("seap-awards", 3, False)
    assert (awards["first_day"], awards["last_day"]) == ("2026-10-05", "2026-10-07")
    # What is held is more than what is counted: every notice, with all its contracts.
    assert awards["counts"] == {"notices": 3, "contracts": 5, "counted_contracts": 3}
    assert direct["counts"] == {"purchases": 6, "accepted": 5, "above_limit": 1}
    assert (awards["days_collected"], awards["days_partial"], awards["documents"]) == (3, 0, 1)
    # The list page only: the pages of single purchases are stored apart.
    assert (direct["days_collected"], direct["documents"]) == (0, 1)
    # Rows the parser could not read: none, two, and not known for files parsed before
    # the count was kept.
    assert (direct["rejected_rows"], awards["rejected_rows"]) == (0, 2)
    assert [each["rejected_rows"] for each in files] == [None, None, 0]


def test_rejected_rows_are_known_only_once_every_document_was_seen(client, session):
    session.add(
        SourceDocument(
            source="seap-direct",
            url="https://example.test/2",
            sha256="e" * 64,
            storage_key="k",
            size_bytes=1,
        )
    )
    session.flush()
    direct = client.get("/v1/datasets").json()["items"][0]
    # One document from before the count: the source's count is not known.
    assert (direct["documents"], direct["rejected_rows"]) == (2, None)
    # Set aside unread by a parser that counts, it no longer stands in the way.
    record_skipped(
        session.scalar(select(SourceDocument).where(SourceDocument.sha256 == "e" * 64)), 3, "test"
    )
    session.flush()
    assert client.get("/v1/datasets").json()["items"][0]["rejected_rows"] == 0
    # The pages of single purchases count with the list pages.
    detail = session.scalar(select(SourceDocument).where(SourceDocument.sha256 == "d3" * 32))
    detail.rejected_rows = 2
    session.flush()
    assert client.get("/v1/datasets").json()["items"][0]["rejected_rows"] == 2


def test_a_day_read_outside_the_period_is_not_counted_with_its_days(client, session):
    """The days read stand next to the period on the site: never "4 of 3 days"."""
    start, end = day_bounds(date(2025, 1, 15))
    session.add(JobRun(job="seap-awards", period_start=start, period_end=end, status="succeeded"))
    session.flush()

    awards = client.get("/v1/datasets").json()["items"][1]
    assert (awards["first_day"], awards["last_day"]) == ("2026-10-05", "2026-10-07")
    assert (awards["days_collected"], awards["days_partial"]) == (3, 0)


def test_a_day_read_in_part_is_told_apart_until_it_is_read_in_full(client, session):
    for day, status in ((8, "partial"), (9, "partial"), (9, "succeeded"), (10, "failed")):
        start, end = day_bounds(date(2026, 10, day))
        session.add(JobRun(job="seap-awards", period_start=start, period_end=end, status=status))
    session.flush()

    awards = client.get("/v1/datasets").json()["items"][1]
    assert (awards["days_collected"], awards["days_partial"]) == (4, 1)


def test_a_buyer_and_a_supplier_have_a_summary_together(client):
    pair = client.get(f"/v1/direct-purchases/summary?buyer={TOWN_HALL}&supplier={BUILDER}").json()
    assert (pair["purchases"], pair["accepted"], pair["value"]) == (2, 2, 3000)
    # A refused offer is counted as a purchase, never as money.
    other = client.get(
        f"/v1/direct-purchases/summary?buyer={TOWN_HALL}&supplier={STATIONER}"
    ).json()
    assert (other["purchases"], other["accepted"], other["value"]) == (2, 1, 500)


def test_the_list_of_purchases_takes_every_filter_and_sorts_by_any_column(client):
    def ids(**params):
        page = client.get("/v1/direct-purchases", params=params).json()
        return [item["id"] for item in page["items"]]

    mine = {"buyer": TOWN_HALL}
    assert ids(**mine, sort="value") == [4, 2, 1, 3]
    assert ids(**mine, sort="value", order="asc") == [3, 1, 2, 4]
    # A party's name, A to Z; the same name keeps the oldest purchase first.
    assert ids(**mine, sort="supplier", order="asc") == [1, 2, 3, 4]
    assert ids(**mine, sort="newest") == ids(**mine) == [4, 3, 2, 1]
    # Words anywhere: the name, the code, the text of a party; case and diacritics aside.
    assert ids(q="lab gmbh") == [6]
    assert ids(q="da00000003") == [3]
    # Several states or types: any of them. A type not known is 0.
    assert ids(**mine, state=[3]) == [4]
    assert ids(**mine, state=[7, 3]) == [4, 3, 2, 1]
    assert ids(**mine, contract_type=[0]) == [4, 3, 2, 1]
    assert ids(**mine, contract_type=[1, 2]) == []
    # From the lower value, under the higher one.
    assert ids(**mine, value_min=1000, value_max=2000) == [1]


def test_the_list_of_one_party_says_what_the_filters_keep_of_it(client):
    def overview(**params):
        return client.get("/v1/direct-purchases/overview", params=params).json()

    town = overview(buyer=TOWN_HALL, scope="buyer")
    found = town["summary"]
    assert (found["purchases"], found["accepted"], found["value"]) == (4, 3, 3500)
    assert town["whole"] == 4
    assert town["last_day_held"] == "2026-10-07"
    # Two days apart: drawn per day, only the accepted purchases counted in totals.
    assert town["step"] == "day"
    assert [(p["start"], p["count"], p["value"]) for p in town["points"]] == [
        ("2026-10-05", 1, 1000),
        ("2026-10-06", 2, 2500),
    ]
    assert town["party"] == "supplier"
    assert [(p["cui"], p["value"]) for p in town["parties"]] == [(BUILDER, 3000), (STATIONER, 500)]
    assert town["others"] == {"parties": 0, "value": 0}
    assert [(o["value"], o["count"]) for o in town["states"]] == [(7, 3), (3, 1)]
    assert [(o["value"], o["count"]) for o in town["contract_types"]] == [(0, 4)]
    assert [b["count"] for b in town["bands"]][:4] == [1, 2, 1, 0]
    assert town["bands"][-1] == {"start": 900400, "end": None, "count": 0}
    assert town["without"] == []

    # An option is counted under every filter but its own.
    some = overview(buyer=TOWN_HALL, scope="buyer", supplier=STATIONER, state=7)
    assert (some["summary"]["purchases"], some["whole"]) == (1, 4)
    assert [(o["value"], o["count"]) for o in some["states"]] == [(3, 1), (7, 1)]

    # Nothing found: what each filter alone keeps out, never the party of the list.
    empty = overview(buyer=TOWN_HALL, scope="buyer", supplier=STATIONER, state=7, value_min=5000)
    assert empty["summary"]["purchases"] == 0
    assert empty["points"] == []
    assert empty["without"] == [
        {"param": "supplier", "count": 0},
        {"param": "state", "count": 1},
        {"param": "value_min", "count": 1},
    ]

    # A purchase above the limit is in no chart; a party with no CUI is among the others.
    hospital = overview(buyer=HOSPITAL, scope="buyer")
    assert (hospital["summary"]["value"], hospital["parties"]) == (700, [])
    assert hospital["others"] == {"parties": 1, "value": 700}
    # The list of a supplier names the buyers.
    assert overview(supplier=BUILDER, scope="supplier")["party"] == "buyer"


def test_the_typeahead_filters_offer_what_the_list_holds(client):
    def parties(**params):
        found = client.get("/v1/direct-purchases/parties", params=params).json()
        return [(p["cui"], p["count"]) for p in found]

    assert parties(buyer=TOWN_HALL, side="supplier") == [(BUILDER, 2), (STATIONER, 2)]
    assert parties(buyer=TOWN_HALL, side="supplier", find="birotica") == [(STATIONER, 2)]
    assert parties(buyer=TOWN_HALL, side="supplier", find=str(BUILDER)) == [(BUILDER, 2)]
    # The side's own filter is left out, so the other options stay.
    assert len(parties(buyer=TOWN_HALL, supplier=BUILDER, side="supplier")) == 2

    def codes(**params):
        found = client.get("/v1/direct-purchases/cpv-codes", params=params).json()
        return [(c["code"], c["count"]) for c in found]

    assert codes(buyer=TOWN_HALL) == [("30192000-1", 3), ("45233140-2", 1)]
    assert codes(buyer=TOWN_HALL, find="4523") == [("45233140-2", 1)]


def test_the_list_of_one_party_downloads_in_its_order(client):
    answer = client.get(
        "/v1/direct-purchases",
        params={"buyer": TOWN_HALL, "sort": "value", "format": "csv"},
    )
    lines = answer.text.lstrip("\ufeff").splitlines()
    assert lines[0].startswith("code,finalized_at,name")
    assert [line.split(",")[0] for line in lines[1:]] == [
        "DA00000004",
        "DA00000002",
        "DA00000001",
        "DA00000003",
    ]
    # The whole register is not a file.
    assert client.get("/v1/direct-purchases", params={"format": "csv"}).status_code == 400


GOODS, SERVICES, WORKS = 1, 2, 3


def add_near_limit(session):
    """Purchases near their limit: 270,120 lei for goods and services, 900,400 for works."""
    doc = session.scalar(select(SourceDocument).where(SourceDocument.source == "seap-direct"))
    rows = [
        purchase(20, HOSPITAL, STATIONER, 7, "250000", "2026-10-05T10:00:00+03:00"),
        purchase(21, HOSPITAL, STATIONER, 7, "265000", "2026-10-06T10:00:00+03:00"),
        # At the limit is not under it; far under it is not near it.
        purchase(22, HOSPITAL, STATIONER, 7, "270120", "2026-10-06T11:00:00+03:00"),
        purchase(23, HOSPITAL, STATIONER, 7, "200000", "2026-10-06T12:00:00+03:00"),
        purchase(
            24,
            TOWN_HALL,
            BUILDER,
            7,
            "850000",
            "2026-10-05T11:00:00+03:00",
            cpv_code="45000000-7",
            cpv_name="Lucrari de constructii",
            contract_type_id=WORKS,
        ),
        purchase(
            25,
            TOWN_HALL,
            BUILDER,
            7,
            "880000",
            "2026-10-07T11:00:00+03:00",
            cpv_code="45233140-2",
            contract_type_id=WORKS,
        ),
        # Once only: no pattern.
        purchase(26, TOWN_HALL, STATIONER, 7, "260000", "2026-10-06T13:00:00+03:00"),
        # Its type is not known, so it cannot be checked, and its day is not in the period.
        purchase(27, HOSPITAL, STATIONER, 7, "260000", "2026-10-08T10:00:00+03:00"),
        # Refused: never money spent.
        purchase(28, HOSPITAL, STATIONER, 3, "260000", "2026-10-07T11:00:00+03:00"),
    ]
    kinds = {20: GOODS, 21: GOODS, 22: GOODS, 23: GOODS, 26: SERVICES, 28: GOODS}
    for row in rows:
        row.source_document_id = doc.id
        row.contract_type_id = row.contract_type_id or kinds.get(row.id)
    session.add_all(rows)
    session.flush()


def test_near_limit_lists_repeated_purchases_just_under_their_own_limit(client, session):
    add_near_limit(session)
    pattern = client.get("/v1/patterns/near-limit").json()
    assert pattern["rule"] == {
        "share": 0.9,
        "repeats": 2,
        "limits": {"1": 270120.0, "2": 270120.0, "3": 900400.0},
    }
    assert pattern["pairs"] == 2
    assert [
        (p["buyer"]["cui"], p["supplier"]["cui"], p["contract_type"], p["purchases"], p["value"])
        for p in pattern["items"]
    ] == [
        (TOWN_HALL, BUILDER, WORKS, 2, 1730000.0),
        (HOSPITAL, STATIONER, GOODS, 2, 515000.0),
    ]
    assert pattern["items"][0]["limit"] == 900400.0
    assert [row["id"] for row in pattern["items"][1]["items"]] == [20, 21]
    # Purchases 1, 2, 3, 5 and 6 of the fixture and 27 here have no type.
    assert (pattern["checked"], pattern["accepted_total"], pattern["unknown_type"]) == (7, 13, 6)
    assert pattern["annex_2"] == 0
    assert (pattern["first_day"], pattern["last_day"]) == ("2026-10-05", "2026-10-07")


def test_near_limit_can_be_narrowed_by_cpv_and_cut_short(client, session):
    add_near_limit(session)
    works = client.get("/v1/patterns/near-limit?cpv=45").json()
    assert [p["supplier"]["cui"] for p in works["items"]] == [BUILDER]
    assert (works["checked"], works["accepted_total"], works["unknown_type"]) == (2, 3, 1)
    assert (works["first_day"], works["last_day"]) == ("2026-10-05", "2026-10-07")
    short = client.get("/v1/patterns/near-limit?limit=1").json()
    assert (short["pairs"], len(short["items"])) == (2, 1)
    assert client.get("/v1/patterns/near-limit?cpv=4x").status_code == 422


def test_rankings_can_be_filtered_by_cpv_and_eu_funds(client):
    def cuis(path):
        return [row["cui"] for row in client.get(path).json()["items"]]

    assert cuis("/v1/rankings/suppliers?cpv=4523") == [STATIONER]
    assert cuis("/v1/rankings/institutions?cpv=4523") == [TOWN_HALL]
    assert cuis("/v1/rankings/contract-institutions?eu_funded=true") == [TOWN_HALL]
    # The notice of the hospital is not read in detail: in neither list.
    assert cuis("/v1/rankings/contract-institutions?eu_funded=false") == []
    assert cuis("/v1/rankings/contract-institutions?cpv=30") == []
    assert cuis("/v1/rankings/contract-suppliers?won=association&cpv=45") == [
        BUILDER,
        STATIONER,
    ]
    largest = client.get("/v1/award-contracts?sort=value&eu_funded=true").json()
    assert [item["id"] for item in largest["items"]] == [101, 103]


def test_a_town_halls_budget_has_lines_that_add_up_to_its_total(client):
    answer = client.get(f"/v1/institutions/{TOWN_HALL}/budget").json()
    assert (answer["place"]["siruta"], answer["place"]["name"], answer["place"]["slug"]) == (
        places_seed.TANTARENI,
        "Comuna Țânțăreni",
        "comuna-tantareni",
    )
    assert answer["located"]["slug"] == "comuna-tantareni"
    budget = answer["budget"]
    assert (budget["year"], budget["executed_on"]) == (2024, "2024-12-31")
    lines = {line["line"]: line["amount"] for line in budget["revenue_lines"]}
    # In the order the site shows them; own revenue is less the income tax shares in it.
    assert list(lines) == [
        "state_subsidies",
        "income_tax",
        "vat",
        "own_revenue",
        "eu_funds",
        "other_administrations",
        "other",
    ]
    assert (lines["income_tax"], lines["own_revenue"]) == (1500000, 1000000)
    assert sum(lines.values()) == budget["revenue"] == 10000000
    assert (budget["spending"], budget["capital"]) == (9800000, 6000000)
    # Chapters largest first; one with nothing spent is left out.
    assert [c["chapter"] for c in budget["chapters"]] == [
        "transport",
        "education",
        "general_services",
    ]
    assert budget["source"]["record"] == "MDLPA · Situația veniturilor și cheltuielilor 2024"
    assert budget["source"]["sha256"] == "5eed" * 16
    payments = answer["programme_payments"]
    # The three payments of project 101; never added to the subsidies.
    assert (payments["payments"], payments["projects"], payments["amount"]) == (3, 1, 5400000)
    assert (payments["first_published"], payments["last_published"]) == ("2026-05-18", "2026-08-27")
    # So the site can open the town hall's projects on the programme page.
    assert (payments["county"], payments["town_hall"]) == ("GORJ", "ȚÂNȚĂRENI")


def test_any_other_institution_has_its_funder_and_no_budget(client):
    answer = client.get(f"/v1/institutions/{HOSPITAL}/budget").json()
    assert answer["place"] is None
    # Not placed: neither the Finance Ministry's list nor ANAF were read for it.
    assert answer["located"] is None
    assert answer["budget"] is None
    assert answer["programme_payments"] is None
    assert answer["funder"]["cui"] == TOWN_HALL
    assert client.get("/v1/institutions/12345674/budget").status_code == 404


def test_a_commune_page_names_each_figure_with_its_own_period(client):
    page = client.get("/v1/places/gorj/comuna-tantareni").json()
    assert page["place"] == {
        "siruta": places_seed.TANTARENI,
        "name": "Comuna Țânțăreni",
        "kind": "commune",
        "slug": "comuna-tantareni",
        "county_slug": "gorj",
        "county": "Gorj",
    }
    assert page["town_hall"]["cui"] == TOWN_HALL
    # Its villages, so the site can check the one a reader searched for.
    assert page["localities"] == ["Țânțăreni", "Florești"]
    figures = page["figures"]
    assert figures["population"] == {"people": 5533, "on": "2024-01-01"}
    assert figures["programme_payments"]["payments"] == 3
    assert (figures["capital"]["amount"], figures["capital"]["year"]) == (6000000, 2024)
    # Contracts signed in the period by every buyer here: the town hall's two counted.
    contracts = figures["contracts"]
    assert (contracts["contracts"], contracts["value"], contracts["buyers"]) == (2, 6330000, 1)
    assert contracts["period"] == {"first_day": "2026-10-05", "last_day": "2026-10-07"}
    # The builder is in Gorj, the stationer in Dolj: their association is counted apart.
    shares = figures["supplier_counties"]
    assert (shares["county"], shares["local"], shares["mixed"], shares["elsewhere"]) == (
        "Gorj",
        210000,
        6120000,
        0,
    )
    top = figures["top_winners"]
    assert [[m["cui"] for m in row["members"]] for row in top] == [
        [BUILDER, STATIONER],
        [BUILDER],
    ]
    assert top[0]["counties"] == ["Gorj", "Dolj"]
    assert page["budget"]["capital"] == 6000000
    assert [(p["id"], p["match"]) for p in page["projects"]] == [(101, "one")]
    assert page["projects"][0]["progress"] == "64%"
    institutions = page["institutions"]
    assert [(i["entity"]["cui"], i["town_hall"], i["contracts"]) for i in institutions] == [
        (TOWN_HALL, True, 2)
    ]


def test_a_county_adds_up_its_uats_and_lists_them(client):
    county = client.get("/v1/places/gorj").json()
    assert county["place"]["name"] == "Gorj"
    # Its council is not among the entities held.
    assert county["council"] is None
    assert county["figures"]["contracts"]["value"] == 6330000
    # The year of the UATs' capital spending, the council's left out.
    assert county["capital_year"] == 2024
    assert [
        (u["place"]["slug"], u["population"], u["capital"], u["contracts"]) for u in county["uats"]
    ] == [("comuna-tantareni", 5533, 6000000, 2)]
    counties = client.get("/v1/places").json()["items"]
    assert [(c["place"]["slug"], c["uats"], c["population"]) for c in counties] == [
        ("gorj", 1, 5533)
    ]
    assert client.get("/v1/places/nimic").status_code == 404
    assert client.get("/v1/places/gorj/comuna-nimic").status_code == 404


def test_a_village_is_found_as_the_commune_it_belongs_to(client):
    def found(q):
        items = client.get(f"/v1/places/search?q={q}").json()["items"]
        return [(item["place"]["slug"], item["village"]) for item in items]

    # The village named like its commune is the commune itself.
    assert found("tantareni") == [("comuna-tantareni", None)]
    assert found("floresti") == [("comuna-tantareni", "Florești")]
    assert found("zzzz") == []


def test_cpv_divisions_are_those_held_with_seap_names(client, session):
    add_near_limit(session)
    assert client.get("/v1/cpv-divisions").json() == [
        {"code": "30", "name": None},
        {"code": "45", "name": "Lucrari de constructii"},
    ]


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
    # The list of direct purchases of an entity page: a page of it and its overview, in
    # the list's own order, sorted by value both ways, filtered by state, emptied by three
    # filters and given back by removing one, filtered by a supplier from the chart, and
    # the options of the supplier filter.
    f"/v1/direct-purchases?buyer={TOWN_HALL}&sort=date&order=desc&limit=25&offset=0",
    f"/v1/direct-purchases/overview?buyer={TOWN_HALL}&scope=buyer",
    f"/v1/direct-purchases?buyer={TOWN_HALL}&sort=value&order=desc&limit=25&offset=0",
    f"/v1/direct-purchases?buyer={TOWN_HALL}&sort=value&order=asc&limit=25&offset=0",
    f"/v1/direct-purchases?buyer={TOWN_HALL}&state=7&sort=date&order=desc&limit=25&offset=0",
    f"/v1/direct-purchases/overview?buyer={TOWN_HALL}&state=7&scope=buyer",
    # An old link to "Cele mai mari acceptate" (?ordine=valoare), and a page past the end,
    # which the site sends back to the last page.
    f"/v1/direct-purchases?buyer={TOWN_HALL}&state=7&sort=value&order=desc&limit=25&offset=0",
    f"/v1/direct-purchases?buyer={TOWN_HALL}&sort=date&order=desc&limit=25&offset=200",
    f"/v1/direct-purchases?buyer={TOWN_HALL}&supplier={STATIONER}&state=7&value_min=5000&sort=date&order=desc&limit=25&offset=0",
    f"/v1/direct-purchases/overview?buyer={TOWN_HALL}&supplier={STATIONER}&state=7"
    "&value_min=5000&scope=buyer",
    f"/v1/direct-purchases?buyer={TOWN_HALL}&supplier={STATIONER}&value_min=5000&sort=date&order=desc&limit=25&offset=0",
    f"/v1/direct-purchases/overview?buyer={TOWN_HALL}&supplier={STATIONER}&value_min=5000"
    "&scope=buyer",
    f"/v1/direct-purchases?buyer={TOWN_HALL}&supplier={BUILDER}&sort=date&order=desc&limit=25&offset=0",
    f"/v1/direct-purchases/overview?buyer={TOWN_HALL}&supplier={BUILDER}&scope=buyer",
    f"/v1/direct-purchases/parties?buyer={TOWN_HALL}&side=supplier",
    f"/v1/suppliers/{BUILDER}?partners=10",
    f"/v1/direct-purchases?supplier={BUILDER}&sort=date&order=desc&limit=25&offset=0",
    f"/v1/direct-purchases/overview?supplier={BUILDER}&scope=supplier",
    "/v1/institutions/12345674?partners=10",
    "/v1/direct-purchases?buyer=12345674&sort=date&order=desc&limit=25&offset=0",
    "/v1/direct-purchases/overview?buyer=12345674&scope=buyer",
    "/v1/rankings/suppliers?limit=20",
    "/v1/rankings/institutions?limit=20",
    "/v1/datasets",
    "/v1/corrections",
    f"/v1/award-notices/{ROAD}",
    f"/v1/award-notices/{ROAD}/contracts?limit=50&offset=0",
    f"/v1/award-notices/{LAB}",
    f"/v1/award-notices/{LAB}/contracts?limit=50&offset=0",
    # A page past the end of the list: the site sends the reader back to the last one.
    f"/v1/award-notices/{LAB}/contracts?limit=50&offset=300",
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
    f"/v1/institutions/{TOWN_HALL}/budget",
    "/v1/institutions/12345674/budget",
    # An institution with no budget held, funded by the town hall.
    f"/v1/institutions/{HOSPITAL}?partners=10",
    f"/v1/institutions/{HOSPITAL}/contracts",
    f"/v1/institutions/{HOSPITAL}/budget",
    f"/v1/award-contracts?buyer={HOSPITAL}&sort=newest&limit=20&offset=0",
    f"/v1/direct-purchases?buyer={HOSPITAL}&sort=date&order=desc&limit=25&offset=0",
    f"/v1/direct-purchases/overview?buyer={HOSPITAL}&scope=buyer",
    # Places: the counties, one county, one commune, a search by name and by village.
    "/v1/places",
    "/v1/places/gorj",
    "/v1/places/gorj/comuna-tantareni",
    "/v1/places/gorj/comuna-nimic",
    "/v1/places/nimic",
    "/v1/places/search?q=tantareni&limit=20",
    "/v1/places/search?q=floresti&limit=20",
    "/v1/search?q=floresti&limit=30",
    "/v1/places/search?q=zzzz&limit=20",
    f"/v1/award-contracts?buyer={TOWN_HALL}&sort=newest&limit=20&offset=0",
    f"/v1/suppliers/{BUILDER}/contracts",
    f"/v1/award-contracts?supplier={BUILDER}&sort=newest&limit=20&offset=0",
    "/v1/institutions/12345674/contracts",
    "/v1/award-contracts?sort=value&limit=20&offset=0",
    "/v1/rankings/contract-suppliers?won=alone&limit=20",
    "/v1/rankings/contract-suppliers?won=association&limit=20",
    "/v1/rankings/contract-institutions?limit=20",
    # The rankings with their filters.
    "/v1/award-contracts?sort=value&cpv=45&limit=20&offset=0",
    "/v1/award-contracts?sort=value&cpv=45&eu_funded=true&limit=20&offset=0",
    "/v1/award-contracts?sort=value&cpv=30&limit=20&offset=0",
    "/v1/rankings/contract-suppliers?won=alone&cpv=45&limit=20",
    "/v1/rankings/contract-institutions?eu_funded=false&limit=20",
    "/v1/rankings/suppliers?cpv=45&limit=20",
    "/v1/rankings/institutions?cpv=45&limit=20",
    "/v1/programmes/anghel-saligny",
    "/v1/programmes/anghel-saligny/projects?limit=20&offset=0",
    "/v1/programmes/anghel-saligny/projects?county=GORJ&limit=20&offset=0",
    "/v1/programmes/anghel-saligny/projects?match=several&limit=20&offset=0",
    "/v1/programmes/anghel-saligny/projects?q=turceni&limit=20&offset=0",
    "/v1/programmes/anghel-saligny/projects?q=zzzz&limit=20&offset=0",
    f"/v1/programmes/anghel-saligny/projects?builder={BUILDER}&limit=20&offset=0",
    # One project per match state, and one the programme does not have.
    "/v1/programmes/anghel-saligny/projects/101",
    "/v1/programmes/anghel-saligny/projects/102",
    "/v1/programmes/anghel-saligny/projects/103",
    "/v1/programmes/anghel-saligny/projects/104",
    "/v1/programmes/anghel-saligny/projects/999",
    "/v1/programmes/pnrr",
    "/v1/programmes/pnrr/measures/C10.I3",
    "/v1/programmes/pnrr/measures/C2.I1",
    "/v1/programmes/pnrr/measures/C99.I9",
    "/v1/programmes/pnrr/contracts?measure=C10.I3&limit=20&offset=0",
    "/v1/programmes/pnrr/contracts?measure=C10.I3&status=finished&limit=20&offset=0",
    "/v1/programmes/pnrr/contracts?measure=C2.I1&limit=20&offset=0",
    f"/v1/programmes/pnrr/contracts/{pnrr_seed.ONE}",
    f"/v1/programmes/pnrr/contracts/{pnrr_seed.SEVERAL}",
    f"/v1/programmes/pnrr/contracts/{pnrr_seed.MANY_MEASURES}",
    f"/v1/programmes/pnrr/contracts/{pnrr_seed.PERSON}",
    "/v1/programmes/eu-funds",
    "/v1/programmes/eu-funds/projects?limit=20&offset=0",
    "/v1/programmes/eu-funds/projects?programme=POR&limit=20&offset=0",
    "/v1/programmes/eu-funds/projects?status=finished&limit=20&offset=0",
    "/v1/programmes/eu-funds/projects?q=zzzz&limit=20&offset=0",
    f"/v1/programmes/eu-funds/projects?q={eu_seed.POR}&limit=20&offset=0",
    # The EU money of a beneficiary, on its institution, supplier and place pages.
    f"/v1/programmes/eu-beneficiaries/{TOWN_HALL}",
    f"/v1/programmes/eu-beneficiaries/{HOSPITAL}",
    f"/v1/programmes/eu-beneficiaries/{BUILDER}",
    # Asked beside the entity, so asked for a CUI not held too.
    "/v1/programmes/eu-beneficiaries/12345674",
    f"/v1/programmes/eu-funds/projects?beneficiary={TOWN_HALL}&limit=20&offset=0",
    f"/v1/programmes/eu-funds/projects?beneficiary={HOSPITAL}&limit=20&offset=0",
    f"/v1/programmes/pnrr/contracts?beneficiary={TOWN_HALL}&limit=20&offset=0",
    # One project per kind of beneficiary tie and payments, and one not held.
    f"/v1/programmes/eu-funds/projects/{eu_seed.PEO}",
    f"/v1/programmes/eu-funds/projects/{eu_seed.POR}",
    f"/v1/programmes/eu-funds/projects/{eu_seed.POCU}",
    f"/v1/programmes/eu-funds/projects/{eu_seed.HEALTH}",
    "/v1/programmes/eu-funds/projects/999999",
    # The SEAP records tied to a project: some, none.
    f"/v1/programmes/eu-funds/projects/{eu_seed.POR}/seap?limit=20&offset=0",
    # A page past the end: the site goes back to the last page.
    f"/v1/programmes/eu-funds/projects/{eu_seed.POR}/seap?limit=20&offset=160",
    # Saved without its SEAP records, so the site's tests see that call fail.
    f"/v1/programmes/eu-funds/projects/{eu_seed.POIM}",
    f"/v1/programmes/eu-funds/projects/{eu_seed.PEO}/seap?limit=20&offset=0",
    f"/v1/programmes/eu-funds/projects/{eu_seed.POCU}/seap?limit=20&offset=0",
    f"/v1/programmes/eu-funds/projects/{eu_seed.HEALTH}/seap?limit=20&offset=0",
    f"/v1/programmes/pnrr/contracts/{pnrr_seed.ONE}/seap?limit=20&offset=0",
    f"/v1/programmes/pnrr/contracts/{pnrr_seed.SEVERAL}/seap?limit=20&offset=0",
    f"/v1/programmes/pnrr/contracts/{pnrr_seed.MANY_MEASURES}/seap?limit=20&offset=0",
)
# Read once the purchases near their limit are added, so the answers above stay as the
# pages that use them expect.
SITE_CALLS_NEAR_LIMIT = (
    "/v1/cpv-divisions",
    "/v1/patterns/near-limit?limit=50",
    "/v1/patterns/near-limit?cpv=45&limit=50",
    "/v1/patterns/near-limit?cpv=30&limit=50",
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


def test_the_site_stub_holds_what_the_api_answers(client, session, monkeypatch):
    """Fails when an answer the site depends on changes.

    Then run `WRITE_SITE_STUB=1 uv run pytest tests/test_api_data.py`, and copy the file to
    `e2e/stub/answers.json` in date-romania-web, where the browser tests will show what the
    change does to the pages.
    """
    monkeypatch.setattr(main, "database_ok", lambda: True)
    answers = {}

    def read(calls):
        for call in calls:
            response = client.get(call)
            answers[call] = {"status": response.status_code, "body": _steady(response.json())}

    read(SITE_CALLS)
    add_near_limit(session)
    read(SITE_CALLS_NEAR_LIMIT)
    text = json.dumps(answers, ensure_ascii=False, indent=1) + "\n"
    if os.environ.get("WRITE_SITE_STUB"):
        SITE_STUB.write_bytes(text.encode("utf-8"))
    assert SITE_STUB.read_text(encoding="utf-8") == text


def test_the_saved_openapi_schema_is_what_the_api_describes():
    """Fails when the shape of an answer or a parameter changes. The site generates its
    types from this file, so a change reaches it as a type error.

    Then run `WRITE_SITE_STUB=1 uv run pytest tests/test_api_data.py`, and copy the file to
    `openapi.json` in date-romania-web, where `pnpm generate-api-types` updates the types.
    """
    text = json.dumps(app.openapi(), ensure_ascii=False, indent=1) + "\n"
    if os.environ.get("WRITE_SITE_STUB"):
        OPENAPI.write_bytes(text.encode("utf-8"))
    assert OPENAPI.read_text(encoding="utf-8") == text


def test_near_limit_as_csv_lists_every_purchase_with_its_pair(client, session):
    add_near_limit(session)
    response = client.get("/v1/patterns/near-limit?format=csv&limit=1")
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "tipare-sub-plafon.csv" in response.headers["content-disposition"]
    lines = response.text.lstrip("﻿").splitlines()
    assert lines[0].startswith("pair,buyer_cui,buyer,supplier_cui,supplier,contract_type")
    # Every pair, whatever the limit of a page: two pairs of two purchases each.
    assert len(lines) == 1 + 4
    assert lines[1].startswith(f"1,{TOWN_HALL},")
    assert ",3,900400.0,2,1730000.0,DA00000024," in lines[1]
    assert ",0.944," in lines[1]
    assert "/direct-acquisition/view/24," in lines[1]
    assert [line.split(",")[0] for line in lines[1:]] == ["1", "1", "2", "2"]
    # The filters of the page carry over.
    works = client.get("/v1/patterns/near-limit?format=csv&cpv=45").text.splitlines()
    assert len(works) == 1 + 2


def test_near_limit_csv_rounds_the_share_down_so_under_the_limit_is_never_1(client, session):
    add_near_limit(session)
    row = purchase(29, HOSPITAL, STATIONER, 7, "270119.60", "2026-10-07T12:00:00+03:00")
    row.source_document_id = session.get(DirectPurchase, 20).source_document_id
    row.contract_type_id = GOODS
    session.add(row)
    session.flush()
    lines = client.get("/v1/patterns/near-limit?format=csv").text.splitlines()
    line = next(line for line in lines if ",DA00000029," in line)
    assert ",270119.6,0.9999," in line


def test_a_total_says_how_many_stored_responses_it_is_added_up_from(client, session):
    # Purchase 5 (the hospital's, from the builder) read from a second response.
    other = SourceDocument(
        source="seap-direct",
        url="https://example.test/b",
        sha256="b" * 64,
        storage_key="k",
        size_bytes=1,
    )
    session.add(other)
    session.flush()
    session.get(DirectPurchase, 5).source_document_id = other.id
    session.flush()

    assert client.get("/v1/stats").json()["source"]["documents"] == 2
    # A figure counts only the responses its own rows come from.
    town_hall = client.get(f"/v1/institutions/{TOWN_HALL}").json()["source"]
    hospital = client.get(f"/v1/institutions/{HOSPITAL}").json()["source"]
    assert (town_hall["documents"], hospital["documents"]) == (1, 2)
    # One record has its file, a total has none.
    assert town_hall["sha256"] is None
    contracts = client.get(f"/v1/institutions/{TOWN_HALL}/contracts").json()["source"]
    assert contracts["documents"] == 1


def test_a_project_lists_the_seap_records_that_cite_it(client):
    tied = client.get(f"/v1/programmes/eu-funds/projects/{eu_seed.POR}/seap").json()
    # Every contract of the road notice, which cites the project's SMIS code; the
    # framework agreement among them, marked as not counted.
    assert tied["contracts_total"] == 4
    assert [row["contract"]["id"] for row in tied["contracts"]] == [103, 101, 102, 104]
    assert {row["cited"] for row in tied["contracts"]} == {"118001"}
    assert {row["method"] for row in tied["contracts"]} == {"smis-in-text"}
    assert {row["confidence"] for row in tied["contracts"]} == {"probable"}
    assert [row["contract"]["counted"] for row in tied["contracts"]] == [True, True, False, True]
    assert tied["purchases"] == []
    page = client.get(
        f"/v1/programmes/eu-funds/projects/{eu_seed.POR}/seap", params={"limit": 2, "offset": 2}
    ).json()
    assert [row["contract"]["id"] for row in page["contracts"]] == [102, 104]
    none = client.get(f"/v1/programmes/eu-funds/projects/{eu_seed.PEO}/seap").json()
    assert none == {"contracts_total": 0, "contracts": [], "purchases": []}
    assert client.get("/v1/programmes/eu-funds/projects/999999/seap").status_code == 404


def test_a_pnrr_contract_lists_the_purchases_of_its_beneficiary_that_cite_it(client):
    tied = client.get(f"/v1/programmes/pnrr/contracts/{pnrr_seed.ONE}/seap").json()
    assert tied["contracts"] == []
    (row,) = tied["purchases"]
    assert row["purchase"]["id"] == 3
    assert (row["cited"], row["method"]) == ("12321/26.08.2024", "financing-number+buyer")
    # The hospital's contract 12345 is cited by no one.
    other = client.get(f"/v1/programmes/pnrr/contracts/{pnrr_seed.SEVERAL}/seap").json()
    assert other["purchases"] == []
    # A natural person's contract has no page, nor its SEAP records.
    assert client.get(f"/v1/programmes/pnrr/contracts/{pnrr_seed.PERSON}/seap").status_code == 404


def test_a_beneficiary_has_its_eu_money_of_both_kinds_apart(client, session):
    town = client.get(f"/v1/programmes/eu-beneficiaries/{TOWN_HALL}").json()
    assert town["entity"]["cui"] == TOWN_HALL
    # Its cohesion projects by programme, each at its own list's day.
    # Tied by the name of its administration, not by a CUI in the list: said so.
    assert [(p["code"], p["projects"], p["by_name"], p["cut_off"]) for p in town["cohesion"]] == [
        ("POR", 1, 1, "2025-08-31")
    ]
    assert town["cohesion_source"]["documents"] == 1
    # Its PNRR contracts, and every payment it received, on any measure.
    pnrr = town["pnrr"]
    assert (pnrr["contracts"], pnrr["total"]) == (2, 6500000)
    assert (pnrr["paid"], pnrr["payments"]) == (2300000, 3)
    assert (pnrr["first_day"], pnrr["last_day"]) == ("2025-12-19", "2026-10-02")
    assert pnrr["edition"] == "2026-10-15"
    hospital = client.get(f"/v1/programmes/eu-beneficiaries/{HOSPITAL}").json()
    assert [(p["code"], p["by_name"]) for p in hospital["cohesion"]] == [("PEO", 0), ("PS", 0)]
    # A company with nothing of either kind.
    builder = client.get(f"/v1/programmes/eu-beneficiaries/{BUILDER}").json()
    assert (builder["cohesion"], builder["cohesion_source"], builder["pnrr"]) == ([], None, None)
    stationer = client.get(f"/v1/programmes/eu-beneficiaries/{STATIONER}").json()
    assert stationer["cohesion"] == []
    assert stationer["pnrr"]["contracts"] == 1
    assert client.get("/v1/programmes/eu-beneficiaries/361684").status_code == 404
    # Paid on a measure where it holds no contract: its payments are still its own.
    session.add(
        PnrrPayment(
            position=99,
            measure_code="C2.I1",
            amount=Decimal("40000"),
            paid_on=date(2026, 4, 1),
            beneficiary_cui=BUILDER,
            natural_person=False,
            contracts_on_measure=0,
            source_document_id=session.scalar(select(PnrrPayment.source_document_id).limit(1)),
            parser_version=1,
        )
    )
    session.flush()
    paid = client.get(f"/v1/programmes/eu-beneficiaries/{BUILDER}").json()["pnrr"]
    assert (paid["contracts"], paid["total"], paid["paid"], paid["payments"]) == (0, None, 40000, 1)
