"""Loading into PostgreSQL, inside a transaction that is rolled back. Skipped with no database."""

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania.collectors.seap_direct import PARSER_VERSION, load, parse_page
from date_romania.db import database_ok, get_engine
from date_romania.models import DirectPurchase, Entity, SourceDocument

FIXTURE = Path(__file__).parent / "fixtures" / "seap_direct_page.json"

pytestmark = pytest.mark.skipif(not database_ok(), reason="needs the PostgreSQL database")


@pytest.fixture
def session():
    with get_engine().connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


def document(session: Session, sha256: str) -> SourceDocument:
    doc = SourceDocument(
        source="test", url="https://example.test", sha256=sha256, storage_key="k", size_bytes=1
    )
    session.add(doc)
    session.flush()
    return doc


def test_load_is_repeatable_and_keeps_the_latest_copy(session):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ids = [item["directAcquisitionId"] for item in data["items"]]
    first, second = document(session, "a" * 64), document(session, "b" * 64)

    load(session, parse_page(data), first.id)
    data["items"][0]["directAcquisitionName"] = "renamed"
    load(session, parse_page(data), second.id)

    rows = session.scalars(select(DirectPurchase).where(DirectPurchase.id.in_(ids))).all()
    assert len(rows) == 7
    assert {row.source_document_id for row in rows} == {second.id}
    assert {row.parser_version for row in rows} == {PARSER_VERSION}
    assert session.get(DirectPurchase, ids[0]).name == "renamed"


def test_load_adds_entities_and_a_buyer_becomes_an_authority(session):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc = document(session, "c" * 64)
    # 17886786 sells in the first purchase; make it the buyer of the second.
    data["items"][1]["contractingAuthority"] = "17886786 B.T.T. TOURS"
    session.merge(Entity(cui=17886786, name="Known name", kind="company"))
    session.flush()

    load(session, parse_page(data), doc.id)
    session.expire_all()

    entity = session.get(Entity, 17886786)
    assert (entity.name, entity.kind) == ("Known name", "authority")
    assert session.get(Entity, 4981310).kind == "authority"
    linked = session.scalar(
        select(func.count()).select_from(DirectPurchase).where(DirectPurchase.buyer_cui == 17886786)
    )
    assert linked >= 1
