"""Error reports from readers. The one place where the API takes something in."""

from fastapi import APIRouter, HTTPException

from date_romania import reports
from date_romania.api.routes.common import Db
from date_romania.api.schemas import Correction, Corrections, ReportIn, ReportReceived
from date_romania.dates import BUCHAREST

router = APIRouter(tags=["reports"])


@router.post("/reports", status_code=201)
def report(body: ReportIn, session: Db) -> ReportReceived:
    """Tell us that something on a page is wrong. A person reads it before anything changes."""
    try:
        filed = reports.file(session, body.page, body.message, body.evidence)
    except reports.QueueFull:
        raise HTTPException(429, "Too many reports in the last hour. Try again later.") from None
    return ReportReceived(id=filed.id)


@router.get("/corrections")
def corrections(session: Db) -> Corrections:
    """What was corrected after a reader's report: the page and what changed, newest first."""
    return Corrections(
        items=[
            Correction(
                page=each.page,
                correction=each.correction,
                corrected_on=each.reviewed_at.astimezone(BUCHAREST).date(),
            )
            for each in reports.corrections(session, 200)
        ]
    )
