"""Loading award notices into PostgreSQL, in a transaction that is rolled back (see conftest.py)."""

import json
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.seap_awards import run
from date_romania.collectors.seap_awards.fetch import CONTRACTS_URL, LIST_URL
from date_romania.collectors.seap_awards.load import load
from date_romania.collectors.seap_awards.parse import parse_contracts, parse_notices
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardWinner,
    Entity,
    JobRun,
    SourceDocument,
)
from date_romania.storage import StoredObject

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def document(session: Session, sha256: str) -> SourceDocument:
    doc = SourceDocument(
        source="test", url="https://example.test", sha256=sha256, storage_key="k", size_bytes=1
    )
    session.add(doc)
    session.flush()
    return doc


def count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_load_is_repeatable_and_replaces_the_winners(session):
    first, second = document(session, "a" * 64), document(session, "b" * 64)
    load(session, parse_notices(fixture("seap_award_notices")), first.id)
    contracts = fixture("seap_award_contracts")
    load(session, parse_contracts(contracts), first.id)
    assert (count(session, AwardNotice), count(session, AwardContract)) == (6, 9)
    assert count(session, AwardWinner) == 17

    # The association loses three members in a later copy of the same contract.
    contracts["items"][0]["winners"] = contracts["items"][0]["winners"][:2]
    load(session, parse_contracts(contracts), second.id)
    session.expire_all()

    assert count(session, AwardContract) == 9
    assert count(session, AwardWinner) == 14
    winners = session.scalars(
        select(AwardWinner)
        .where(AwardWinner.contract_id == 108187624)
        .order_by(AwardWinner.position)
    ).all()
    assert [winner.supplier_cui for winner in winners] == [15148952, 15425816]
    assert {winner.source_document_id for winner in winners} == {second.id}
    assert session.get(AwardContract, 108187624).source_document_id == second.id


def test_load_adds_buyers_as_authorities_and_winners_as_companies(session):
    doc = document(session, "c" * 64)
    load(session, parse_notices(fixture("seap_award_notices")), doc.id)
    load(session, parse_contracts(fixture("seap_award_contracts")), doc.id)

    assert session.get(Entity, 4364349).kind == "authority"
    assert session.get(Entity, 4491776).kind == "company"
    foreign = session.scalars(select(AwardWinner).where(AwardWinner.country == "Hungary")).one()
    assert foreign.supplier_cui is None


def test_collect_day_stores_every_answer_and_can_rebuild_from_them(session, monkeypatch):
    notices, contracts = fixture("seap_award_notices"), fixture("seap_award_contracts")
    stored: dict[str, bytes] = {}

    def put_raw(source, content, content_type=None):
        import hashlib

        sha = hashlib.sha256(content).hexdigest()
        stored[f"{source}/{sha}"] = content
        return StoredObject(key=f"{source}/{sha}", sha256=sha, size_bytes=len(content))

    monkeypatch.setattr("date_romania.collectors.jobs.put_raw", put_raw)
    monkeypatch.setattr(run, "get_raw", lambda key: stored[key])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if str(request.url) == LIST_URL:
            return httpx.Response(200, json=notices)
        assert str(request.url) == CONTRACTS_URL
        items = [item for item in contracts["items"] if item["caNoticeId"] == body["caNoticeId"]]
        return httpx.Response(200, json={"total": len(items), "items": items})

    transport = httpx.MockTransport(handler)
    with PoliteClient(transport=transport, sleep=lambda seconds: None) as client:
        assert run.collect_day(session, client, date(2026, 10, 8)) == 6

    job = session.scalars(select(JobRun).where(JobRun.job == run.JOB)).one()
    assert (job.status, job.records) == ("succeeded", 6)
    assert (count(session, AwardContract), count(session, AwardWinner)) == (9, 17)
    # One list page, four notices with contracts, and one shared empty answer for the two
    # notices with none.
    docs = session.scalars(select(SourceDocument).where(SourceDocument.source == run.SOURCE)).all()
    assert len(docs) == 6
    assert [doc.url for doc in docs].count(LIST_URL) == 1

    session.execute(AwardWinner.__table__.delete())
    session.execute(AwardContract.__table__.delete())
    assert run.reparse(session) == 6
    assert (count(session, AwardContract), count(session, AwardWinner)) == (9, 17)
