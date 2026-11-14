"""Collecting Eurostat's COFOG table for Romania, and loading it again from the raw store."""

import logging

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from date_romania.collectors.cofog.parse import PARSER_VERSION, URL, parse
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, record_parse, store_document, stored_documents
from date_romania.dates import today
from date_romania.models import CofogSpending, SourceDocument
from date_romania.sources import EUROSTAT_COFOG
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = EUROSTAT_COFOG.key


def _load(session: Session, doc: SourceDocument) -> int:
    """The table holds one answer: emptied and filled again, since Eurostat revises the
    years before."""
    parsed = parse(get_raw(doc.storage_key))
    record_parse(doc, parsed.rejected, PARSER_VERSION)
    stamp = {"source_document_id": doc.id, "parser_version": PARSER_VERSION}
    session.execute(delete(CofogSpending))
    if parsed.rows:
        session.execute(insert(CofogSpending), [{**row, **stamp} for row in parsed.rows])
    session.commit()
    years = sorted({row["year"] for row in parsed.rows})
    log.info(
        "COFOG: %d figures, %s to %s, updated %s; %d rejected",
        len(parsed.rows),
        years[0] if years else None,
        years[-1] if years else None,
        parsed.updated_at,
        len(parsed.rejected),
    )
    return len(parsed.rows)


def collect(session: Session, client: PoliteClient) -> int:
    """Ask Eurostat for the table and load it when the answer is new; returns its figures,
    or 0 when the answer is the one held. One small request."""
    with job_run(session, JOB, today()) as run:
        response = client.request("GET", URL)
        held = {doc.id for doc in stored_documents(session, SOURCE)}
        doc = store_document(session, SOURCE, URL, response.content, None, "application/json")
        session.commit()
        if doc.id in held and doc.parser_version == PARSER_VERSION:
            log.info("COFOG: the answer is the one held")
            return 0
        run.records = _load(session, doc)
    return run.records


def reparse(session: Session) -> int:
    """Load the newest stored answer again, without calling Eurostat."""
    docs = stored_documents(session, SOURCE)
    if not docs:
        return 0
    _load(session, docs[-1])
    return 1
