"""Collecting one day, and rebuilding rows from the raw store."""

import json
import logging
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, record_parse, store_document
from date_romania.collectors.seap_awards.fetch import (
    CAP,
    CONTRACTS_URL,
    DETAIL_URL,
    LIST_URL,
    VERSIONS_URL,
    Page,
    SeapError,
    contract_pages,
    detail_page,
    notice_pages,
    versions_page,
)
from date_romania.collectors.seap_awards.load import load
from date_romania.collectors.seap_awards.parse import (
    PARSER_VERSION,
    Parsed,
    parse_contracts,
    parse_detail,
    parse_notices,
    parse_versions,
)
from date_romania.dates import today
from date_romania.models import AwardNotice, AwardNoticeDetail, AwardNoticeVersion, SourceDocument
from date_romania.sources import SEAP_AWARDS
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = SEAP_AWARDS.key
DETAILS_JOB = f"{JOB}-details"


def _parse(data: dict | list, url: str) -> Parsed:
    """Every kind of answer is stored under one source; the address tells them apart."""
    if url == LIST_URL:
        return parse_notices(data)
    if url == CONTRACTS_URL:
        return parse_contracts(data)
    if url.startswith(DETAIL_URL):
        return parse_detail(data, int(url.removeprefix(DETAIL_URL)))
    if url.startswith(VERSIONS_URL):
        return parse_versions(data, int(url.removeprefix(VERSIONS_URL)))
    raise ValueError(f"no parser for {url}")


def _parse_and_load(
    session: Session, data: dict | list, doc: SourceDocument, url: str | None = None
) -> Parsed:
    """`url` is the address just asked. Two addresses that answer with the same bytes
    share one document, which keeps only the first address, so the document's own is used
    only when rebuilding from the raw store.
    """
    parsed = _parse(data, url or doc.url)
    record_parse(doc, parsed.rejected, PARSER_VERSION)
    load(session, parsed, doc.id)
    return parsed


def _store_and_load(session: Session, page: Page) -> Parsed:
    doc = store_document(
        session, SOURCE, page.url, page.content, page.request_body, "application/json"
    )
    parsed = _parse_and_load(session, page.data, doc, page.url)
    session.commit()
    return parsed


def collect_day(session: Session, client: PoliteClient, day: date) -> int:
    """Fetch, store and load every award notice published on `day`; returns how many."""
    with job_run(session, JOB, day) as run:
        notices: set[int] = set()
        contracts = invalid_cuis = no_detail = 0
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
            # The notice and its contracts are saved by now. A detail that fails is left
            # to `collect_details`, so that the day is not fetched all over again.
            try:
                _collect_detail(session, client, notice_id)
            except (SeapError, httpx.HTTPError) as exc:
                session.rollback()
                no_detail += 1
                log.warning("notice %d: no detail: %r", notice_id, exc)
        run.records = len(notices)
        if truncated:
            run.status = "partial"
            run.error = f"the list stopped at its cap of {CAP}: the day is incomplete"
        log.info(
            "%s: %d notices with %d contracts, %d names without a valid CUI, "
            "%d notices left without their detail",
            day,
            len(notices),
            contracts,
            invalid_cuis,
            no_detail,
        )
    return len(notices)


def _collect_detail(session: Session, client: PoliteClient, notice_id: int) -> None:
    """The detail and the versions of one notice: two more requests."""
    _store_and_load(session, detail_page(client, notice_id))
    _store_and_load(session, versions_page(client, notice_id))


def collect_details(session: Session, client: PoliteClient, limit: int | None = None) -> int:
    """Fetch the detail and the versions of the notices that lack either; returns how many.

    For notices collected before the detail was, and for the ones a failed day left
    behind. One notice that fails does not stop the rest: the run ends as `partial` and
    the next run takes it up again.
    """
    have_detail = select(AwardNoticeDetail.notice_id)
    have_versions = select(AwardNoticeVersion.notice_id)
    todo = session.scalars(
        select(AwardNotice.id)
        .where(AwardNotice.id.not_in(have_detail) | AwardNotice.id.not_in(have_versions))
        .order_by(AwardNotice.id)
        .limit(limit)
    ).all()
    with job_run(session, DETAILS_JOB, today()) as run:
        # Counted here, not on the run: a rollback would take back what was not yet saved.
        done = failed = 0
        for notice_id in todo:
            try:
                _collect_detail(session, client, notice_id)
            except (SeapError, httpx.HTTPError) as exc:
                session.rollback()
                failed += 1
                log.warning("notice %d: %r", notice_id, exc)
                continue
            done += 1
            if done % 100 == 0:
                log.info("%d of %d notices", done, len(todo))
        run.records = done
        if failed:
            run.status = "partial"
            run.error = f"{failed} of {len(todo)} notices failed; run again to retry them"
    return done


def reparse(session: Session) -> int:
    """Rebuild the rows from the raw store, oldest file first, without calling SEAP."""
    docs = session.scalars(
        select(SourceDocument).where(SourceDocument.source == SOURCE).order_by(SourceDocument.id)
    ).all()
    for doc in docs:
        _parse_and_load(session, json.loads(get_raw(doc.storage_key)), doc)
        session.commit()
    return len(docs)
