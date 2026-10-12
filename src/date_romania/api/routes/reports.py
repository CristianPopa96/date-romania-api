"""Error reports from readers. The one place where the API takes something in."""

from fastapi import APIRouter, HTTPException, Request

from date_romania import reports
from date_romania.api.routes.common import Db
from date_romania.api.schemas import Correction, Corrections, ReportIn, ReportReceived
from date_romania.dates import BUCHAREST

router = APIRouter(tags=["reports"])


@router.post("/reports", status_code=201)
def report(body: ReportIn, request: Request, session: Db) -> ReportReceived:
    """Tell us that something on a page is wrong. A person reads it before anything changes.

    A reader may send a few reports an hour. The site passes the reader's address on in
    `X-Forwarded-For`; a call made straight to the API counts under the caller's own.
    """
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    address = forwarded or (request.client.host if request.client else None)
    try:
        filed = reports.file(session, body.page, body.message, body.evidence, address)
    except reports.QueueFull:
        raise HTTPException(429, "Too many reports in the last hour. Try again later.") from None
    return ReportReceived(id=filed.id)


@router.get("/corrections")
def corrections(session: Db) -> Corrections:
    """What was corrected after a reader's report: the page and what changed, newest first."""
    return Corrections(
        items=[
            Correction(
                page=reports.site_page(each.page),
                correction=each.correction,
                corrected_on=each.reviewed_at.astimezone(BUCHAREST).date(),
            )
            for each in reports.corrections(session, 200)
        ]
    )
