"""Error reports from readers: taking one in, and the review that settles it.

A report says what a reader believes is wrong on a page. Nothing a reader wrote is ever
shown on the site: once someone has checked a report and corrected the data, what is
published is our own words for what changed, and the page only when it is the address of
a page the site has.
"""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania.models import Report
from date_romania.personal_id import mask_cnp

NEW, ACCEPTED, REJECTED = "new", "accepted", "rejected"

# The form is open to anyone, so the queue takes only so many reports an hour: a few
# from one reader, so that one program cannot shut the others out, and a total, because a
# person reads each one and more than this is not readers finding errors.
PER_READER_HOUR = 5
PER_HOUR = 60

# A reader is told apart by a keyed hash of their address, never by the address. The key
# lives only in this process, so a stored value cannot be turned back into an address, and
# says nothing once the API has restarted. It only has to hold for the hour of the limit.
_KEY = secrets.token_bytes(32)

# The pages the site has. A page is published with its correction only if it is one of
# these; anything else typed into the field stays in the queue, for the reviewer alone.
_PAGE = re.compile(
    r"/(?:(?:contracte|achizitii-directe|institutii|furnizori)/\d+|clasamente|surse|cautare)?"
)
# Characters that act on a terminal or hide text; a new line and a tab are kept.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


class QueueFull(Exception):
    """More reports arrived in the last hour than the queue takes."""


def reader(address: str | None) -> str | None:
    """What stands for a reader's address in the queue: a hash that cannot be undone."""
    if not address:
        return None
    return hmac.new(_KEY, address.encode(), hashlib.sha256).hexdigest()


def site_page(page: str | None) -> str | None:
    """The address of a page of the site, without what follows `?` or `#`; else nothing."""
    path = re.split(r"[?#]", (page or "").strip(), maxsplit=1)[0]
    return path if _PAGE.fullmatch(path) else None


def _clean(text: str | None) -> str | None:
    """A reader's text as it is stored: no control characters, no personal numeric codes."""
    return mask_cnp(_CONTROL.sub("", text or "").strip(), checked=True) or None


def file(
    session: Session,
    page: str | None,
    message: str,
    evidence: str | None,
    address: str | None = None,
) -> Report:
    """Put a report in the queue, unless the last hour already brought too many."""
    since = Report.created_at >= datetime.now(UTC) - timedelta(hours=1)
    sender = reader(address)
    recent, own = session.execute(
        select(func.count(), func.count().filter(Report.sender == sender)).where(since)
    ).one()
    if recent >= PER_HOUR or (sender and own >= PER_READER_HOUR):
        raise QueueFull
    report = Report(
        page=_clean(page),
        message=_clean(message) or "",
        evidence=_clean(evidence),
        sender=sender,
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
    session: Session,
    report_id: int,
    status: str,
    correction: str | None = None,
    page: str | None = None,
) -> Report | None:
    """Close a report as accepted, with what was corrected, or as rejected.

    `page` is the reviewer's own address for the page, where the reader gave none we can
    publish.
    """
    report = session.get(Report, report_id)
    if report is None:
        return None
    report.status = status
    report.correction = correction
    if page:
        report.page = page
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
