"""Collecting one day, and rebuilding rows from the raw store."""

import logging
from datetime import date

import httpx
from sqlalchemy.orm import Session

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import (
    job_run,
    record_parse,
    store_document,
    stored_documents,
    stored_json,
)
from date_romania.collectors.seap_direct import details
from date_romania.collectors.seap_direct.load import load
from date_romania.collectors.seap_direct.parse import (
    DETAIL_PARSER_VERSION,
    PARSER_VERSION,
    Parsed,
    parse_detail,
    parse_page,
)
from date_romania.collectors.seap_direct.slices import (
    CAP,
    LIST_URL,
    contract_type_of,
    fetch,
    iter_pages,
)
from date_romania.dates import today
from date_romania.models import PARTIAL, SourceDocument
from date_romania.sources import SEAP_DIRECT

log = logging.getLogger(__name__)

SOURCE = JOB = SEAP_DIRECT.key
DETAILS_JOB = f"{JOB}-details"


def _parse_and_load(
    session: Session, data: dict, doc: SourceDocument, url: str | None = None
) -> Parsed:
    """List pages and the details of purchases are stored under one source; the address
    tells them apart. `url` is the address just asked: two answers with the same bytes
    share one document, which keeps only the first address.
    """
    url = url or doc.url
    if url.startswith(details.DETAIL_URL):
        parsed = parse_detail(data, int(url.removeprefix(details.DETAIL_URL)))
        record_parse(doc, parsed.rejected, DETAIL_PARSER_VERSION)
    else:
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


def collect_details(session: Session, client: PoliteClient, limit: int | None = None) -> int:
    """Fetch, store and load the detail of the purchases `details.due()` gives; returns how
    many.

    One purchase that fails does not stop the rest: the run ends as `partial` and the next
    run asks again. Many failures in a row stop the run: SEAP is refusing, not one purchase.
    """
    todo = details.due(session, limit)
    with job_run(session, DETAILS_JOB, today()) as run:
        # Counted here, not on the run: a rollback would take back what was not yet saved.
        done = failed = in_a_row = 0
        for purchase_id in todo:
            try:
                answer = details.fetch(client, purchase_id)
                doc = store_document(
                    session, SOURCE, answer.url, answer.content, None, "application/json"
                )
                _parse_and_load(session, answer.data, doc, answer.url)
                session.commit()
            except (details.SeapError, httpx.HTTPError) as exc:
                session.rollback()
                failed += 1
                in_a_row += 1
                log.warning("purchase %d: %r", purchase_id, exc)
                if in_a_row == details.MAX_FAILURES_IN_A_ROW:
                    log.error("%d failures in a row: stopped until the next run", in_a_row)
                    break
                continue
            done += 1
            in_a_row = 0
            if done % 500 == 0:
                log.info("%d of %d purchases", done, len(todo))
        run.records = done
        if failed:
            run.status = PARTIAL
            run.error = f"{failed} of {len(todo)} purchases failed; run again to retry them"
    log.info("%d purchase details collected, %d failed", done, failed)
    return done


def reparse(session: Session) -> int:
    """Rebuild the rows from the raw store, oldest file first, without calling SEAP."""
    docs = stored_documents(session, SOURCE)
    for doc in docs:
        _parse_and_load(session, stored_json(doc), doc)
        session.commit()
    return len(docs)
