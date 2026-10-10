"""Collecting one day, and rebuilding rows from the raw store."""

import json
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, store_document
from date_romania.collectors.seap_awards.fetch import (
    CAP,
    LIST_URL,
    Page,
    contract_pages,
    notice_pages,
)
from date_romania.collectors.seap_awards.load import load
from date_romania.collectors.seap_awards.parse import Parsed, parse_contracts, parse_notices
from date_romania.models import SourceDocument
from date_romania.sources import SEAP_AWARDS
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = SEAP_AWARDS.key


def _parse_and_load(session: Session, data: dict, doc: SourceDocument) -> Parsed:
    """Both kinds of answer are stored under one source; the address tells them apart."""
    parsed = parse_notices(data) if doc.url == LIST_URL else parse_contracts(data)
    for item, reason in parsed.rejected:
        log.warning("source_document %d: rejected row %s: %.500r", doc.id, reason, item)
    load(session, parsed, doc.id)
    return parsed


def _store_and_load(session: Session, page: Page) -> Parsed:
    doc = store_document(
        session, SOURCE, page.url, page.content, page.request_body, "application/json"
    )
    parsed = _parse_and_load(session, page.data, doc)
    session.commit()
    return parsed


def collect_day(session: Session, client: PoliteClient, day: date) -> int:
    """Fetch, store and load every award notice published on `day`; returns how many."""
    with job_run(session, JOB, day) as run:
        notices: set[int] = set()
        contracts = invalid_cuis = 0
        truncated = False
        for page in notice_pages(client, day):
            parsed = _store_and_load(session, page)
            notices.update(row["id"] for row in parsed.notices)
            invalid_cuis += parsed.invalid_cuis
            truncated |= page.truncated
        for notice_id in sorted(notices):
            for page in contract_pages(client, notice_id):
                parsed = _store_and_load(session, page)
                contracts += len(parsed.contracts)
                invalid_cuis += parsed.invalid_cuis
        run.records = len(notices)
        if truncated:
            run.status = "partial"
            run.error = f"the list stopped at its cap of {CAP}: the day is incomplete"
        log.info(
            "%s: %d notices with %d contracts, %d names without a valid CUI",
            day,
            len(notices),
            contracts,
            invalid_cuis,
        )
    return len(notices)


def reparse(session: Session) -> int:
    """Rebuild the rows from the raw store, oldest file first, without calling SEAP."""
    docs = session.scalars(
        select(SourceDocument).where(SourceDocument.source == SOURCE).order_by(SourceDocument.id)
    ).all()
    for doc in docs:
        _parse_and_load(session, json.loads(get_raw(doc.storage_key)), doc)
        session.commit()
    return len(docs)
