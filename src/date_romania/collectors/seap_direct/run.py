"""Collecting one day, and rebuilding rows from the raw store."""

import logging
from datetime import date

from sqlalchemy.orm import Session

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import (
    job_run,
    record_parse,
    store_document,
    stored_documents,
    stored_json,
)
from date_romania.collectors.seap_direct.load import load
from date_romania.collectors.seap_direct.parse import PARSER_VERSION, Parsed, parse_page
from date_romania.collectors.seap_direct.slices import (
    CAP,
    LIST_URL,
    contract_type_of,
    fetch,
    iter_pages,
)
from date_romania.models import PARTIAL, SourceDocument
from date_romania.sources import SEAP_DIRECT

log = logging.getLogger(__name__)

SOURCE = JOB = SEAP_DIRECT.key


def _parse_and_load(session: Session, data: dict, doc: SourceDocument) -> Parsed:
    parsed = parse_page(data, contract_type_of(doc.request_body))
    record_parse(doc, parsed.rejected, PARSER_VERSION)
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
            run.status = PARTIAL
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
    docs = stored_documents(session, SOURCE)
    for doc in docs:
        _parse_and_load(session, stored_json(doc), doc)
        session.commit()
    return len(docs)
