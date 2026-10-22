"""Collecting a PNRR edition into PostgreSQL, inside a transaction that is rolled back."""

import gzip
import hashlib
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from test_pnrr import DAY, ONE, PERSON, SEVERAL, TWO_MEASURES

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.pnrr import run
from date_romania.collectors.pnrr.fetch import INDEX_URL, url_of
from date_romania.collectors.pnrr.parse import ENDPOINTS
from date_romania.models import (
    Entity,
    JobRun,
    PnrrContract,
    PnrrContractLine,
    PnrrEdition,
    PnrrMeasure,
    PnrrPayment,
    PnrrTopRecipient,
    SourceDocument,
)
from date_romania.storage import StoredObject

FIXTURES = Path(__file__).parent / "fixtures" / "pnrr"


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def no_sleep(seconds: float) -> None:
    pass


@pytest.fixture
def raw_store(monkeypatch) -> dict[str, bytes]:
    """The raw store, in memory: stored bytes by their hash."""
    stored: dict[str, bytes] = {}

    def put_raw(source, content, content_type=None):
        sha256 = hashlib.sha256(content).hexdigest()
        stored[sha256] = content
        return StoredObject(key=sha256, sha256=sha256, size_bytes=len(content))

    monkeypatch.setattr("date_romania.collectors.jobs.put_raw", put_raw)
    monkeypatch.setattr("date_romania.collectors.pnrr.run.get_raw", lambda key: stored[key])
    monkeypatch.setattr("date_romania.collectors.pnrr.run.places.locate", lambda session: None)
    return stored


def mipe(asked: list[str], edit=None) -> httpx.MockTransport:
    """The dashboard's files: the fixture edition, gzipped, and its index."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        if url == INDEX_URL:
            files = [{"file": f"20261015-{endpoint}.json.gz"} for endpoint in ENDPOINTS]
            return httpx.Response(200, json={"files": files})
        for endpoint in ENDPOINTS:
            if url == url_of(DAY, endpoint):
                data = json.loads((FIXTURES / f"20261015-{endpoint}.json").read_text("utf-8"))
                if edit:
                    edit(endpoint, data)
                return httpx.Response(200, content=gzip.compress(json.dumps(data).encode()))
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_collect_loads_an_edition_once(session, raw_store):
    asked: list[str] = []
    with PoliteClient(transport=mipe(asked), sleep=no_sleep) as client:
        assert run.collect(session, client) == 5
    assert len(asked) == 1 + len(ENDPOINTS)
    assert session.get(PnrrEdition, DAY).contracts == 21710
    assert (count(session, PnrrContract), count(session, PnrrContractLine)) == (5, 6)
    assert (count(session, PnrrMeasure), count(session, PnrrPayment)) == (6, 4)
    assert count(session, PnrrTopRecipient) == 3
    job = session.scalars(select(JobRun).where(JobRun.job == run.JOB)).one()
    assert (job.status, job.records) == ("succeeded", 5)

    # The same edition again: only the index is asked for, nothing is loaded.
    asked.clear()
    with PoliteClient(transport=mipe(asked), sleep=no_sleep) as client:
        assert run.collect(session, client) == 0
    assert asked == [INDEX_URL]


def test_an_older_edition_never_replaces_a_newer_one(session, raw_store):
    """If MIPE's index fell back to an older edition, the one held stays."""
    with PoliteClient(transport=mipe([]), sleep=no_sleep) as client:
        run.collect(session, client)
    session.get(PnrrEdition, DAY).day = date(2026, 11, 1)
    session.flush()
    asked: list[str] = []
    with PoliteClient(transport=mipe(asked), sleep=no_sleep) as client:
        assert run.collect(session, client) == 0
    assert asked == [INDEX_URL]
    assert session.scalars(select(PnrrEdition.day)).all() == [date(2026, 11, 1)]


def test_payments_are_tied_and_beneficiaries_become_entities(session, raw_store):
    with PoliteClient(transport=mipe([]), sleep=no_sleep) as client:
        run.collect(session, client)
    payments = session.scalars(select(PnrrPayment).order_by(PnrrPayment.position)).all()
    assert [(p.contracts_on_measure, p.contract_id) for p in payments] == [
        (1, ONE),
        (2, None),
        (0, None),
        (0, None),
    ]
    person = session.get(PnrrContract, PERSON)
    assert (person.natural_person, person.beneficiary_cui) == (True, None)
    one = session.get(PnrrContract, ONE)
    assert session.get(Entity, one.beneficiary_cui).kind == "authority"
    shared = session.get(PnrrContract, SEVERAL[0])
    assert session.get(Entity, shared.beneficiary_cui) is not None
    lines = session.scalars(
        select(PnrrContractLine.measure_code).where(PnrrContractLine.contract_id == TWO_MEASURES)
    ).all()
    assert len(set(lines)) == 2


def test_a_row_on_a_measure_not_listed_is_rejected_not_fatal(session, raw_store):
    def unknown_measure(endpoint, data):
        if endpoint == "plati_pnrr":
            data[0]["cod_masura"] = "I99"

    with PoliteClient(transport=mipe([], unknown_measure), sleep=no_sleep) as client:
        assert run.collect(session, client) == 5
    assert count(session, PnrrPayment) == 3
    doc = session.scalar(
        select(SourceDocument).where(SourceDocument.url == url_of(DAY, "plati_pnrr"))
    )
    assert doc.rejected_rows == 1


def test_reparse_loads_the_stored_edition_again(session, raw_store):
    with PoliteClient(transport=mipe([]), sleep=no_sleep) as client:
        run.collect(session, client)
    session.execute(PnrrPayment.__table__.delete())
    assert run.reparse(session) == len(ENDPOINTS)
    assert count(session, PnrrPayment) == 4
