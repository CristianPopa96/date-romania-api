"""The data endpoints, over a handful of purchases in a throwaway schema (see conftest.py)."""

from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from date_romania.api.main import app
from date_romania.db import get_session
from date_romania.models import DirectPurchase, Entity, SourceDocument

TOWN_HALL, HOSPITAL = 4981310, 4491342
BUILDER, STATIONER = 17886786, 18288250


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
