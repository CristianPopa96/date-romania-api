"""Collecting the newest SIRUTA edition, and rebuilding the places from the raw store."""

import logging

from sqlalchemy.orm import Session

from date_romania import places
from date_romania.collectors import datagov
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, record_parse, stored_documents
from date_romania.collectors.siruta.parse import PARSER_VERSION, parse_places
from date_romania.dates import today
from date_romania.db import upsert_rows
from date_romania.models import Place, SourceDocument
from date_romania.sources import SIRUTA
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = SIRUTA.key


def _parse_and_load(session: Session, doc: SourceDocument) -> int:
    parsed = parse_places(get_raw(doc.storage_key))
    record_parse(doc, parsed.rejected, PARSER_VERSION)
    stamp = {"source_document_id": doc.id, "parser_version": PARSER_VERSION}
    upsert_rows(session, Place, [{**row, **stamp} for row in parsed.places], ("siruta",))
    session.commit()
    log.info("%s: %d places, %d rows rejected", doc.url, len(parsed.places), len(parsed.rejected))
    return len(parsed.places)


def collect(session: Session, client: PoliteClient) -> int:
    """Fetch the CSV of the newest edition if it is not held, and load it; returns the
    places it brought. A place renamed or merged keeps its old row."""
    with job_run(session, JOB, today()) as run:
        dataset = datagov.newest_dataset(client, "siruta", "siruta")
        csvs = [
            each for each in datagov.resources(client, dataset) if each.url.lower().endswith(".csv")
        ]
        if not csvs:
            raise datagov.DatagovError(f"{dataset}: no CSV file")
        doc, new = datagov.fetch(session, client, SOURCE, csvs[-1])
        if new:
            try:
                run.records = _parse_and_load(session, doc)
            except Exception:
                datagov.forget(session, doc)
                raise
    places.locate(session)
    session.commit()
    return run.records


def reparse(session: Session) -> int:
    """Load every stored edition again, oldest first, without calling data.gov.ro."""
    docs = stored_documents(session, SOURCE)
    for doc in docs:
        _parse_and_load(session, doc)
    places.locate(session)
    session.commit()
    return len(docs)
