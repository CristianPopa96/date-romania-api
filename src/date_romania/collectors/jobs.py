"""Run bookkeeping shared by collectors: which days are missing, and one `job_run` row per run."""

import json
import logging
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania.dates import BUCHAREST, day_bounds
from date_romania.models import FAILED, RUNNING, SUCCEEDED, JobRun, SourceDocument, done_days
from date_romania.storage import StoredObject, get_raw, put_raw, put_raw_file

log = logging.getLogger(__name__)


def missing_days(done: set[date], last: date, first: date | None = None) -> list[date]:
    """Days from `first` up to `last` that are not in `done`.

    `first` is the first day ever tried, so a first run that failed is tried again; without
    it, the first day done. With no history only `last` is due: older days come from bulk
    exports, not from a first run.
    """
    first = first or min(done, default=None)
    if first is None:
        return [last]
    return [
        day
        for day in (first + timedelta(days=n) for n in range((last - first).days + 1))
        if day not in done
    ]


def tried_days(session: Session, job: str) -> set[date]:
    """The days `job` has a run for, whatever its status."""
    query = select(JobRun.period_start).where(JobRun.job == job)
    return {
        start.astimezone(BUCHAREST).date() for start in session.scalars(query) if start is not None
    }


def due_days(
    session: Session, job: str, last: date, day: date | None = None, since: date | None = None
) -> list[date]:
    """The days to fetch now: one day, every day from `since`, or the ones missed so far."""
    if day:
        return [day]
    if since:
        return missing_days(set(), last, first=since)
    tried = tried_days(session, job)
    return missing_days(set(done_days(session, job)), last, first=min(tried, default=None))


def collect_days(
    days: Iterable[date], collect_day: Callable[[date], int], report: Callable[[date, int], None]
) -> list[date]:
    """Collect each day in turn and return the days that failed.

    One day that keeps failing must not hold back the days after it.
    """
    failed = []
    for day in days:
        try:
            count = collect_day(day)
        except Exception:
            log.exception("%s: failed", day)
            failed.append(day)
        else:
            report(day, count)
    return failed


def store_document(
    session: Session,
    source: str,
    url: str,
    content: bytes,
    request_body: str | None = None,
    content_type: str | None = None,
) -> SourceDocument:
    """Keep the raw bytes and return their `source_document` row; same bytes, same row."""
    stored = put_raw(source, content, content_type)
    return _document(session, source, url, stored, request_body, content_type)


def store_file(
    session: Session,
    source: str,
    url: str,
    path: Path,
    request_body: str | None = None,
    content_type: str | None = None,
) -> SourceDocument:
    """`store_document` for a file too large to hold in memory."""
    stored = put_raw_file(source, path, content_type)
    return _document(session, source, url, stored, request_body, content_type)


def _document(
    session: Session,
    source: str,
    url: str,
    stored: StoredObject,
    request_body: str | None,
    content_type: str | None,
) -> SourceDocument:
    doc = session.scalar(select(SourceDocument).where(SourceDocument.sha256 == stored.sha256))
    if doc is None:
        doc = SourceDocument(
            source=source,
            url=url,
            request_body=request_body,
            sha256=stored.sha256,
            storage_key=stored.key,
            content_type=content_type,
            size_bytes=stored.size_bytes,
        )
        session.add(doc)
        session.flush()
    return doc


def stored_documents(session: Session, source: str) -> list[SourceDocument]:
    """Every stored document of `source`, oldest first: what a reparse reads again."""
    return list(
        session.scalars(
            select(SourceDocument)
            .where(SourceDocument.source == source)
            .order_by(SourceDocument.id)
        )
    )


def stored_json(doc: SourceDocument) -> object:
    """A stored JSON answer, read back from the raw store."""
    return json.loads(get_raw(doc.storage_key))


def record_parse(
    doc: SourceDocument, rejected: list[tuple[object, str]], parser_version: int
) -> None:
    """Log each row the parser could not read, and keep on the document how many there
    were and which parser read it, so the sources page can show them. Never drop a row
    silently: every parse of a stored document goes through here.
    """
    for row, reason in rejected:
        log.warning("source_document %d: rejected row %s: %.500r", doc.id, reason, row)
    doc.parser_version = parser_version
    doc.rejected_rows = len(rejected)


def record_skipped(doc: SourceDocument, parser_version: int, reason: str) -> None:
    """Mark a stored document as seen and set aside by this parser, unread: its source's
    count of rejected rows is then complete without it.
    """
    log.info("source_document %d: not read: %s", doc.id, reason)
    doc.parser_version = parser_version
    doc.rejected_rows = None


@contextmanager
def job_run(session: Session, job: str, day: date) -> Iterator[JobRun]:
    """Record one run for one day. The caller sets `records`; a raised error marks it failed.

    The caller sets the status to `partial` when it knows the day is incomplete.
    """
    start, end = day_bounds(day)
    run = JobRun(job=job, period_start=start, period_end=end, status=RUNNING, records=0)
    session.add(run)
    session.commit()
    try:
        yield run
    except Exception as exc:
        session.rollback()
        run.status, run.error = FAILED, repr(exc)[:2000]
        run.finished_at = datetime.now(UTC)
        session.commit()
        raise
    if run.status == RUNNING:
        run.status = SUCCEEDED
    run.finished_at = datetime.now(UTC)
    session.commit()
