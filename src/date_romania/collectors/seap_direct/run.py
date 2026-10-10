"""Collecting one day, and rebuilding rows from the raw store."""

import json
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, store_document
from date_romania.collectors.seap_direct.load import load
from date_romania.collectors.seap_direct.parse import Parsed, parse_page
from date_romania.collectors.seap_direct.slices import CAP, LIST_URL, fetch, iter_pages
from date_romania.models import SourceDocument
from date_romania.sources import SEAP_DIRECT
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = SEAP_DIRECT.key


def _parse_and_load(session: Session, data: dict, doc: SourceDocument) -> Parsed:
    parsed = parse_page(data)
    for item, reason in parsed.rejected:
        log.warning("source_document %d: rejected row %s: %.500r", doc.id, reason, item)
    load(session, parsed, doc.id)
    return parsed


def collect_day(session: Session, client: PoliteClient, day: date) -> int:
    """Fetch, store and load every direct purchase finalized on `day`; returns how many."""
    with job_run(session, JOB, day) as run:
        ids: set[int] = set()
        pages = truncated = invalid_cuis = missing_deadlines = 0
        for page in iter_pages(day, lambda sl, size: fetch(client, sl, size)):
            doc = store_document(
                session, SOURCE, LIST_URL, page.content, page.request_body, "application/json"
            )
            parsed = _parse_and_load(session, page.data, doc)
            session.commit()
            ids.update(row["id"] for row in parsed.purchases)
            pages += 1
            truncated += page.truncated
            invalid_cuis += parsed.invalid_cuis
            missing_deadlines += parsed.missing_deadlines
        run.records = len(ids)
        if truncated:
            run.status = "partial"
            run.error = f"{truncated} slices stayed over the cap of {CAP}: the day is incomplete"
        if missing_deadlines:
            log.warning(
                "%s: %d rows lack a deadline where one is expected; "
                "slices split by deadline may have missed such rows",
                day,
                missing_deadlines,
            )
        log.info(
            "%s: %d purchases in %d pages, %d names without a valid CUI",
            day,
            len(ids),
            pages,
            invalid_cuis,
        )
    return len(ids)


def reparse(session: Session) -> int:
    """Rebuild the rows from the raw store, oldest file first, without calling SEAP."""
    docs = session.scalars(
        select(SourceDocument).where(SourceDocument.source == SOURCE).order_by(SourceDocument.id)
    ).all()
    for doc in docs:
        _parse_and_load(session, json.loads(get_raw(doc.storage_key)), doc)
        session.commit()
    return len(docs)
