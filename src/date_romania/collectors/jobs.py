"""Run bookkeeping shared by collectors: which days are missing, and one `job_run` row per run."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania.models import JobRun, SourceDocument
from date_romania.storage import put_raw

# Public sources publish by Romanian calendar day.
BUCHAREST = ZoneInfo("Europe/Bucharest")


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=BUCHAREST)
    return start, datetime.combine(day + timedelta(days=1), time.min, tzinfo=BUCHAREST)


def yesterday() -> date:
    return datetime.now(BUCHAREST).date() - timedelta(days=1)


def missing_days(done: set[date], last: date) -> list[date]:
    """Days up to `last` with no successful run, counted from the first day ever collected.

    With no history only `last` is due: older days come from bulk exports, not from a first run.
    """
    if not done:
        return [last]
    first = min(done)
    return [
        day
        for day in (first + timedelta(days=n) for n in range((last - first).days + 1))
        if day not in done
    ]


def succeeded_days(session: Session, job: str) -> set[date]:
    starts = session.scalars(
        select(JobRun.period_start).where(JobRun.job == job, JobRun.status == "succeeded")
    )
    return {start.astimezone(BUCHAREST).date() for start in starts if start is not None}


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
    """Record one run for one day. The caller sets `records`; a raised error marks it failed."""
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
    run.status = "succeeded"
    run.finished_at = datetime.now(UTC)
    session.commit()
