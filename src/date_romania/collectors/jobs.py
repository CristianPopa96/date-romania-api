"""Run bookkeeping shared by collectors: which days are missing, and one `job_run` row per run."""

import logging
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania.dates import BUCHAREST, day_bounds
from date_romania.models import JobRun, SourceDocument
from date_romania.storage import put_raw

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


# A partial day is not fetched again by itself: the source would cut it at the same place.
DONE = ("succeeded", "partial")


def run_days(session: Session, job: str, *statuses: str) -> set[date]:
    """The days `job` has a run for, in any of `statuses` (all of them if none is given)."""
    query = select(JobRun.period_start).where(JobRun.job == job)
    if statuses:
        query = query.where(JobRun.status.in_(statuses))
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
    tried = run_days(session, job)
    return missing_days(run_days(session, job, *DONE), last, first=min(tried, default=None))


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


@contextmanager
def job_run(session: Session, job: str, day: date) -> Iterator[JobRun]:
    """Record one run for one day. The caller sets `records`; a raised error marks it failed.

    The caller sets the status to `partial` when it knows the day is incomplete.
    """
    start, end = day_bounds(day)
    run = JobRun(job=job, period_start=start, period_end=end, status="running", records=0)
    session.add(run)
    session.commit()
    try:
        yield run
    except Exception as exc:
        session.rollback()
        run.status, run.error = "failed", repr(exc)[:2000]
        run.finished_at = datetime.now(UTC)
        session.commit()
        raise
    if run.status == "running":
        run.status = "succeeded"
    run.finished_at = datetime.now(UTC)
    session.commit()
