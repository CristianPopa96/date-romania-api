"""Loading award notices into PostgreSQL, in a transaction that is rolled back (see conftest.py)."""

import hashlib
import json
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.seap_awards import run
from date_romania.collectors.seap_awards.fetch import (
    CONTRACTS_URL,
    DETAIL_URL,
    LIST_URL,
    VERSIONS_URL,
    Page,
)
from date_romania.collectors.seap_awards.load import load
from date_romania.collectors.seap_awards.parse import (
    parse_contracts,
    parse_detail,
    parse_notices,
    parse_versions,
)
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardNoticeDetail,
    AwardNoticeVersion,
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
        sha = hashlib.sha256(content).hexdigest()
        stored[f"{source}/{sha}"] = content
        return StoredObject(key=f"{source}/{sha}", sha256=sha, size_bytes=len(content))

    monkeypatch.setattr("date_romania.collectors.jobs.put_raw", put_raw)
    monkeypatch.setattr("date_romania.collectors.jobs.get_raw", lambda key: stored[key])

    transport = seap(notices, contracts)
    with PoliteClient(transport=transport, sleep=lambda seconds: None) as client:
        assert run.collect_day(session, client, date(2026, 10, 8)) == 6

    job = session.scalars(select(JobRun).where(JobRun.job == run.JOB)).one()
    assert (job.status, job.records) == ("succeeded", 6)
    assert (count(session, AwardContract), count(session, AwardWinner)) == (9, 17)
    assert (count(session, AwardNoticeDetail), count(session, AwardNoticeVersion)) == (6, 6)
    # One list page, four notices with contracts, one shared empty answer for the two
    # notices with none, then a detail and a list of versions for each of the six.
    docs = session.scalars(select(SourceDocument).where(SourceDocument.source == run.SOURCE)).all()
    assert len(docs) == 6 + 12
    assert [doc.url for doc in docs].count(LIST_URL) == 1

    for model in (AwardWinner, AwardContract, AwardNoticeDetail, AwardNoticeVersion):
        session.execute(model.__table__.delete())
    assert run.reparse(session) == 18
    assert (count(session, AwardContract), count(session, AwardWinner)) == (9, 17)
    assert (count(session, AwardNoticeDetail), count(session, AwardNoticeVersion)) == (6, 6)


def test_load_keeps_one_detail_and_replaces_the_versions(session):
    first, second = document(session, "d" * 64), document(session, "e" * 64)
    load(session, parse_notices(fixture("seap_award_notices")), first.id)
    detail = fixture("seap_award_details")["plain"]
    versions = fixture("seap_award_versions")["many"]

    load(session, parse_detail(detail), first.id)
    load(session, parse_versions(versions, 100660082), first.id)
    assert (count(session, AwardNoticeDetail), count(session, AwardNoticeVersion)) == (1, 15)

    # A later answer: the buyer now names the notice that opened the procedure, and SEAP
    # lists three versions fewer.
    detail["caNoticeEdit_New"]["publicationDetailsModel"]["noticeNo"] = "CN1"
    load(session, parse_detail(detail), second.id)
    load(session, parse_versions(versions[:12], 100660082), second.id)
    session.expire_all()

    stored = session.get(AwardNoticeDetail, 100660082)
    assert (stored.call_notice_no, stored.source_document_id) == ("CN1", second.id)
    assert (stored.eu_funded, stored.financing_types, stored.eu_funds) == (None, [], [])
    assert (count(session, AwardNoticeDetail), count(session, AwardNoticeVersion)) == (1, 12)
    # Loading the list again must not lose the detail.
    load(session, parse_notices(fixture("seap_award_notices")), second.id)
    assert count(session, AwardNoticeDetail) == 1


def seap(notices: dict, contracts: dict, broken: set[int] = frozenset()) -> httpx.MockTransport:
    """SEAP as the fixtures tell it: every notice has the same plain detail and one version."""
    detail = fixture("seap_award_details")["plain"]
    version = fixture("seap_award_versions")["one"][0]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == LIST_URL:
            return httpx.Response(200, json=notices)
        if url == CONTRACTS_URL:
            wanted = json.loads(request.content)["caNoticeId"]
            items = [item for item in contracts["items"] if item["caNoticeId"] == wanted]
            return httpx.Response(200, json={"total": len(items), "items": items})
        notice_id = int(url.rsplit("/", 1)[1])
        if url.startswith(DETAIL_URL):
            if notice_id in broken:
                return httpx.Response(200, text="<html>not today</html>")
            return httpx.Response(200, json={**detail, "caNoticeID": notice_id})
        assert url.startswith(VERSIONS_URL)
        return httpx.Response(200, json=[{**version, "caNoticeID": notice_id}])

    return httpx.MockTransport(handler)


def test_collect_details_fills_what_is_missing_and_goes_on_past_a_failure(session, monkeypatch):
    monkeypatch.setattr(
        "date_romania.collectors.jobs.put_raw",
        lambda source, content, content_type=None: StoredObject(
            key="k", sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content)
        ),
    )
    notices, contracts = fixture("seap_award_notices"), fixture("seap_award_contracts")
    load(session, parse_notices(notices), document(session, "f" * 64).id)

    broken = seap(notices, contracts, broken={100660193})
    with PoliteClient(transport=broken, sleep=lambda seconds: None) as client:
        assert run.collect_details(session, client) == 5
    job = session.scalars(select(JobRun).where(JobRun.job == run.DETAILS_JOB)).one()
    assert (job.status, job.records) == ("partial", 5)
    assert "1 of 6" in job.error
    assert (count(session, AwardNoticeDetail), count(session, AwardNoticeVersion)) == (5, 5)

    # The next run asks only for the notice left behind.
    with PoliteClient(transport=seap(notices, contracts), sleep=lambda seconds: None) as client:
        assert run.collect_details(session, client) == 1
        assert run.collect_details(session, client) == 0
    assert (count(session, AwardNoticeDetail), count(session, AwardNoticeVersion)) == (6, 6)
    assert session.get(AwardNoticeDetail, 100660193).lots == 1


def test_collect_day_goes_on_past_a_detail_that_fails(session, monkeypatch):
    monkeypatch.setattr(
        "date_romania.collectors.jobs.put_raw",
        lambda source, content, content_type=None: StoredObject(
            key="k", sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content)
        ),
    )
    notices, contracts = fixture("seap_award_notices"), fixture("seap_award_contracts")

    broken = seap(notices, contracts, broken={100660193})
    with PoliteClient(transport=broken, sleep=lambda seconds: None) as client:
        assert run.collect_day(session, client, date(2026, 10, 8)) == 6

    # The day is done, with every notice and contract; one notice waits for its detail.
    job = session.scalars(select(JobRun).where(JobRun.job == run.JOB)).one()
    assert (job.status, job.records) == ("succeeded", 6)
    assert (count(session, AwardNotice), count(session, AwardContract)) == (6, 9)
    assert count(session, AwardNoticeDetail) == 5

    with PoliteClient(transport=seap(notices, contracts), sleep=lambda seconds: None) as client:
        assert run.collect_details(session, client) == 1
    assert (count(session, AwardNoticeDetail), count(session, AwardNoticeVersion)) == (6, 6)


def test_versions_with_the_same_bytes_go_to_the_notice_asked(session, monkeypatch):
    """Two answers with the same bytes share a document; each still loads its own notice."""
    monkeypatch.setattr(
        "date_romania.collectors.jobs.put_raw",
        lambda source, content, content_type=None: StoredObject(
            key="k", sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content)
        ),
    )
    load(session, parse_notices(fixture("seap_award_notices")), document(session, "a" * 64).id)
    first, second = session.scalars(select(AwardNotice.id).order_by(AwardNotice.id).limit(2)).all()
    content = json.dumps([{"caNoticeID": 5, "sysNoticeState": {"id": 10, "text": "Retras"}}])

    for notice_id in (first, second):
        url = f"{VERSIONS_URL}{notice_id}"
        run._store_and_load(session, Page(url, None, content.encode(), json.loads(content)))

    held = session.scalars(select(AwardNoticeVersion.notice_id)).all()
    assert sorted(held) == [first, second]
    assert count(session, SourceDocument) == 2  # the one of the notices, and the shared answer


def test_collect_details_stops_at_the_limit(session, monkeypatch):
    monkeypatch.setattr(
        "date_romania.collectors.jobs.put_raw",
        lambda source, content, content_type=None: StoredObject(
            key="k", sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content)
        ),
    )
    notices = fixture("seap_award_notices")
    load(session, parse_notices(notices), document(session, "0" * 64).id)

    transport = seap(notices, fixture("seap_award_contracts"))
    with PoliteClient(transport=transport, sleep=lambda seconds: None) as client:
        assert run.collect_details(session, client, limit=2) == 2
    assert count(session, AwardNoticeDetail) == 2
