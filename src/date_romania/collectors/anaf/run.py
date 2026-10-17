"""Asking ANAF about every entity not asked yet, and rebuilding the records from the raw
store."""

import json
import logging
from datetime import date
from itertools import batched

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania import places
from date_romania.collectors.anaf.parse import PARSER_VERSION, is_answer, parse_answer
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import (
    job_run,
    record_parse,
    record_skipped,
    store_document,
    stored_documents,
)
from date_romania.dates import today
from date_romania.db import upsert_rows
from date_romania.models import PARTIAL, AnafRecord, Entity, SourceDocument
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
    so a run that stops keeps what it got.

    An answer that is not ANAF's JSON (a "Request Rejected" or maintenance page, sent
    with HTTP 200) is not stored: the run stops there and ends `partial`, and the next
    run asks for the rest.
    """
    day = today()
    with job_run(session, JOB, day) as run:
        cuis = due(session)[:limit]
        asked = 0
        for batch in batched(cuis, BATCH):
            body = json.dumps([{"cui": cui, "data": day.isoformat()} for cui in batch])
            response = client.request(
                "POST", URL, content=body, headers={"Content-Type": "application/json"}
            )
            if not is_answer(response.content):
                run.status = PARTIAL
                run.error = (
                    f"ANAF answered without its JSON ({response.headers.get('content-type')}, "
                    f"{response.content[:200]!r}); {len(cuis) - asked} tax IDs left"
                )
                break
            doc = store_document(
                session, SOURCE, URL, response.content, body, response.headers.get("content-type")
            )
            run.records += _load(session, doc)
            asked += len(batch)
        log.info("%s: %d of %d tax IDs asked", JOB, asked, len(cuis))
        places.locate(session)
    return run.records


def reparse(session: Session) -> int:
    """Load every stored answer again, oldest first: a newer answer replaces an older.
    An answer that cannot be read is set aside, never stops the ones after it."""
    docs = stored_documents(session, SOURCE)
    for doc in docs:
        if is_answer(get_raw(doc.storage_key)):
            _load(session, doc)
        else:
            record_skipped(doc, PARSER_VERSION, "not ANAF's JSON")
            session.commit()
    places.locate(session)
    session.commit()
    return len(docs)
