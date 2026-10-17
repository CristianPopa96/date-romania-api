"""Collecting the newest SIRUTA edition, and rebuilding the places from the raw store."""

import logging

from sqlalchemy.orm import Session

from date_romania import places
from date_romania.collectors import datagov
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, record_parse, stored_documents
from date_romania.collectors.siruta.parse import PARSER_VERSION, edition, parse_places
from date_romania.dates import today
from date_romania.db import upsert_rows
from date_romania.models import Place, SourceDocument
from date_romania.sources import SIRUTA
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = SIRUTA.key


def _file(url: str) -> str:
    return url.rsplit("/", 1)[-1]


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
    places it brought. The edition is told by its file name ('siruta_s1_2026.csv'),
    never by when a dataset was last edited. A place renamed or merged keeps its row."""
    with job_run(session, JOB, today()) as run:
        csvs = [
            each
            for dataset in datagov.datasets(client, "siruta", "siruta")
            for each in datagov.resources(client, dataset)
            if each.url.lower().endswith(".csv") and edition(_file(each.url))
        ]
        if not csvs:
            raise datagov.DatagovError("no SIRUTA edition found")
        newest = max(csvs, key=lambda each: edition(_file(each.url)))
        doc, new = datagov.fetch(session, client, SOURCE, newest)
        if new:
            try:
                run.records = _parse_and_load(session, doc)
            except Exception:
                datagov.forget(session, doc)
                raise
        places.locate(session)
    return run.records


def reparse(session: Session) -> int:
    """Load every stored edition again, oldest edition first so the newest has the last
    word, without calling data.gov.ro."""
    docs = sorted(
        stored_documents(session, SOURCE),
        key=lambda doc: (edition(_file(doc.url)) or (0, 0), doc.id),
    )
    for doc in docs:
        _parse_and_load(session, doc)
    places.locate(session)
    session.commit()
    return len(docs)
