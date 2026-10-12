"""Error reports from readers: taking one in, and the review that settles it.

A report says what a reader believes is wrong on a page. Nothing a reader wrote is ever
shown on the site: once someone has checked a report and corrected the data, what is
published is the page and our own words for what changed.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania.models import Report
from date_romania.personal_id import mask_cnp

NEW, ACCEPTED, REJECTED = "new", "accepted", "rejected"

# The form is open to anyone, so the queue takes only so many reports an hour. A person
# reads each one; more than this is not readers finding errors.
PER_HOUR = 60


class QueueFull(Exception):
    """More reports arrived in the last hour than the queue takes."""


def file(session: Session, page: str | None, message: str, evidence: str | None) -> Report:
    """Put a report in the queue. Personal numeric codes in its text are hidden first."""
    since = datetime.now(UTC) - timedelta(hours=1)
    recent = session.scalar(
        select(func.count()).select_from(Report).where(Report.created_at >= since)
    )
    if recent >= PER_HOUR:
        raise QueueFull
    report = Report(
        page=mask_cnp(page, checked=True) or None,
        message=mask_cnp(message, checked=True),
        evidence=mask_cnp(evidence, checked=True) or None,
        status=NEW,
    )
    session.add(report)
    session.commit()
    return report


def queue(session: Session, settled: bool = False) -> list[Report]:
    """The reports waiting for review, oldest first; with `settled`, every report."""
    query = select(Report).order_by(Report.id)
    if not settled:
        query = query.where(Report.status == NEW)
    return list(session.scalars(query))


def settle(
    session: Session, report_id: int, status: str, correction: str | None = None
) -> Report | None:
    """Close a report as accepted, with what was corrected, or as rejected."""
    report = session.get(Report, report_id)
    if report is None:
        return None
    report.status = status
    report.correction = correction
    report.reviewed_at = datetime.now(UTC)
    session.commit()
    return report


def corrections(session: Session, limit: int) -> list[Report]:
    """The accepted reports, newest correction first."""
    return list(
        session.scalars(
            select(Report)
            .where(Report.status == ACCEPTED)
            .order_by(Report.reviewed_at.desc(), Report.id.desc())
            .limit(limit)
        )
    )
