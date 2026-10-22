"""Loading into PostgreSQL, inside a transaction that is rolled back (see conftest.py)."""

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, tried_days
from date_romania.collectors.seap_direct import run
from date_romania.collectors.seap_direct.load import load
from date_romania.collectors.seap_direct.parse import PARSER_VERSION, parse_page
from date_romania.models import (
    DirectPurchase,
    DirectPurchaseDetail,
    DirectPurchaseItem,
    Entity,
    JobRun,
    SourceDocument,
    done_days,
)
from date_romania.storage import StoredObject

FIXTURE = Path(__file__).parent / "fixtures" / "seap_direct_page.json"
DETAIL = Path(__file__).parent / "fixtures" / "seap_direct_detail.json"


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


def test_a_purchase_keeps_the_type_a_query_asked_for(session):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first = data["items"][0]["directAcquisitionId"]
    typed, untyped = document(session, "e" * 64), document(session, "f" * 64)

    load(session, parse_page(data, contract_type=3), typed.id)
    # Read again by a query that did not filter by type: the type stays.
    load(session, parse_page(data), untyped.id)
    session.expire_all()

    row = session.get(DirectPurchase, first)
    assert (row.contract_type_id, row.source_document_id) == (3, untyped.id)


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


def test_job_run_records_how_each_day_ended(session):
    job = "test-job-statuses"
    with job_run(session, job, date(2026, 10, 1)) as run:
        run.records = 3
    with job_run(session, job, date(2026, 10, 2)) as run:
        run.status = "partial"
    with pytest.raises(RuntimeError), job_run(session, job, date(2026, 10, 3)):
        raise RuntimeError("source is down")

    # A partial day counts as done but not read in full, a failed one is not done, and
    # all three were tried.
    assert done_days(session, job) == {date(2026, 10, 1): True, date(2026, 10, 2): False}
    assert tried_days(session, job) == {date(2026, 10, d) for d in (1, 2, 3)}


def test_a_parse_keeps_on_its_document_what_it_rejected_and_which_parser(session):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["items"][0] = {"directAcquisitionName": "no id"}
    data["items"][1]["finalizationDate"] = "not a date"
    doc = document(session, "c" * 64)
    assert (doc.parser_version, doc.rejected_rows) == (None, None)

    run._parse_and_load(session, data, doc)
    assert (doc.parser_version, doc.rejected_rows) == (PARSER_VERSION, 2)
    # A later parse that reads every row sets it back to none.
    run._parse_and_load(session, json.loads(FIXTURE.read_text(encoding="utf-8")), doc)
    assert doc.rejected_rows == 0


def held_purchases(session: Session) -> list[int]:
    """The fixture's purchases, oldest first, all accepted and small but for four: the two
    oldest accepted at 150,000 lei, the third at 99,999, the fourth refused at 500,000."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    load(session, parse_page(data), document(session, "0" * 64).id)
    ids = sorted(session.scalars(select(DirectPurchase.id)))
    for n, purchase_id in enumerate(ids):
        session.execute(
            update(DirectPurchase)
            .where(DirectPurchase.id == purchase_id)
            .values(
                state_id=7,
                closing_value=1000,
                published_at=datetime(2026, 10, 1, 10) + timedelta(hours=n),
            )
        )
    for purchase_id, state, value in [
        (ids[0], 7, 150_000),
        (ids[1], 7, 150_000),
        (ids[2], 7, 99_999),
        (ids[3], 3, 500_000),
    ]:
        session.execute(
            update(DirectPurchase)
            .where(DirectPurchase.id == purchase_id)
            .values(state_id=state, closing_value=value)
        )
    return ids


def seap(broken: frozenset[int] = frozenset()) -> httpx.MockTransport:
    """SEAP's purchase pages: the fixture, under the id asked; 403 unless the request
    names the purchase's public page."""

    def handler(request: httpx.Request) -> httpx.Response:
        purchase_id = int(request.url.path.rsplit("/", 1)[1])
        page = f"https://e-licitatie.ro/pub/direct-acquisition/view/{purchase_id}"
        if request.headers.get("Referer") != page:
            return httpx.Response(403)
        if purchase_id in broken:
            return httpx.Response(404)
        data = json.loads(DETAIL.read_text(encoding="utf-8"))
        data["directAcquisitionID"] = purchase_id
        return httpx.Response(200, json=data)

    return httpx.MockTransport(handler)


@pytest.fixture
def raw_store(monkeypatch) -> dict[str, bytes]:
    """The raw store, in memory: stored bytes by their hash."""
    stored: dict[str, bytes] = {}

    def put_raw(source, content, content_type=None):
        sha256 = hashlib.sha256(content).hexdigest()
        stored[sha256] = content
        return StoredObject(key=sha256, sha256=sha256, size_bytes=len(content))

    monkeypatch.setattr("date_romania.collectors.jobs.put_raw", put_raw)
    monkeypatch.setattr(
        "date_romania.collectors.seap_direct.run.stored_json",
        lambda doc: json.loads(stored[doc.sha256]),
    )
    return stored


def details_held(session: Session) -> list[int]:
    return list(session.scalars(select(DirectPurchaseDetail.purchase_id)))


def no_sleep(seconds: float) -> None:
    pass


def test_collect_details_asks_only_for_accepted_purchases_of_100000_lei_or_more(session, raw_store):
    ids = held_purchases(session)
    with PoliteClient(transport=seap(broken=frozenset({ids[0]})), sleep=no_sleep) as client:
        assert run.collect_details(session, client) == 1
    job = session.scalars(select(JobRun).where(JobRun.job == run.DETAILS_JOB)).one()
    assert (job.status, job.records) == ("partial", 1)
    assert "1 of 2" in job.error
    assert details_held(session) == [ids[1]]
    lines = session.scalars(select(DirectPurchaseItem.position).order_by("position")).all()
    assert lines == [1, 2, 3]

    # The next run asks only for the one left behind.
    with PoliteClient(transport=seap(), sleep=no_sleep) as client:
        assert run.collect_details(session, client) == 1
        assert run.collect_details(session, client) == 0
    assert sorted(details_held(session)) == ids[:2]


def test_collect_details_asks_for_the_newest_first_and_stops_at_the_limit(session, raw_store):
    ids = held_purchases(session)
    with PoliteClient(transport=seap(), sleep=no_sleep) as client:
        assert run.collect_details(session, client, limit=1) == 1
    assert details_held(session) == [ids[1]]


def test_collect_details_stops_when_seap_refuses_every_purchase(session, raw_store, monkeypatch):
    monkeypatch.setattr("date_romania.collectors.seap_direct.details.MAX_FAILURES_IN_A_ROW", 1)
    held_purchases(session)
    asked = []

    def refuse(request: httpx.Request) -> httpx.Response:
        asked.append(request.url)
        return httpx.Response(403)

    with PoliteClient(transport=httpx.MockTransport(refuse), sleep=no_sleep) as client:
        assert run.collect_details(session, client) == 0
    assert len(asked) == 1


def test_a_reparse_reads_list_pages_and_purchase_pages_apart(session, raw_store):
    ids = held_purchases(session)
    with PoliteClient(transport=seap(), sleep=no_sleep) as client:
        run.collect_details(session, client)
    session.execute(delete(DirectPurchaseDetail))
    assert session.scalar(select(func.count()).select_from(DirectPurchaseItem)) == 0

    run.reparse(session)
    assert sorted(details_held(session)) == ids[:2]
    assert session.scalar(select(func.count()).select_from(DirectPurchaseItem)) == 6
