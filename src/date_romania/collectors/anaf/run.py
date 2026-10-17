"""Asking ANAF about every entity not asked yet, and rebuilding the records from the raw
store."""

import json
import logging
from datetime import date
from itertools import batched

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania import places
from date_romania.collectors.anaf.parse import PARSER_VERSION, parse_answer
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, record_parse, store_document, stored_documents
from date_romania.dates import today
from date_romania.db import upsert_rows
from date_romania.models import AnafRecord, Entity, SourceDocument
from date_romania.sources import ANAF
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = ANAF.key
URL = "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva"
BATCH = 100  # ANAF's limit per call
# A tax ID has at most 10 digits. A longer number would be a personal code, which is
# never sent anywhere.
_LARGEST_CUI = 9_999_999_999


def _load(session: Session, doc: SourceDocument) -> int:
    asked_on = date.fromisoformat(json.loads(doc.request_body)[0]["data"])
    parsed = parse_answer(get_raw(doc.storage_key), asked_on)
    record_parse(doc, parsed.rejected, PARSER_VERSION)
    stamp = {"source_document_id": doc.id, "parser_version": PARSER_VERSION, "siruta": None}
    upsert_rows(session, AnafRecord, [{**row, **stamp} for row in parsed.records], ("cui",))
    session.commit()
    return len(parsed.records)


def due(session: Session) -> list[int]:
    """The entities ANAF was not asked about yet, by tax ID."""
    asked = select(AnafRecord.cui)
    return list(
        session.scalars(
            select(Entity.cui)
            .where(Entity.cui.not_in(asked), Entity.cui <= _LARGEST_CUI)
            .order_by(Entity.cui)
        )
    )


def collect(session: Session, client: PoliteClient, limit: int | None = None) -> int:
    """Ask ANAF about the entities not asked yet, 100 to a call, one call a second;
    returns the records stored. Each answer is stored and loaded before the next call,
    so a run that stops keeps what it got."""
    day = today()
    with job_run(session, JOB, day) as run:
        cuis = due(session)[:limit]
        for batch in batched(cuis, BATCH):
            body = json.dumps([{"cui": cui, "data": day.isoformat()} for cui in batch])
            response = client.request(
                "POST", URL, content=body, headers={"Content-Type": "application/json"}
            )
            doc = store_document(
                session, SOURCE, URL, response.content, body, response.headers.get("content-type")
            )
            run.records += _load(session, doc)
        log.info("%s: %d tax IDs asked", JOB, len(cuis))
    places.locate(session)
    session.commit()
    return run.records


def reparse(session: Session) -> int:
    """Load every stored answer again, oldest first: a newer answer replaces an older."""
    docs = stored_documents(session, SOURCE)
    for doc in docs:
        _load(session, doc)
    places.locate(session)
    session.commit()
    return len(docs)
