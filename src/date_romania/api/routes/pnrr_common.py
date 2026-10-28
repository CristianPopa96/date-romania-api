"""What the PNRR endpoints share: the dashboard's statuses, the edition every figure comes
from, a contract's measures added up, and a measure found by its code.

Natural persons never appear by name (Crispy, 22.10.2026); text is served with valid
personal codes masked (`masked`).
"""

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania.api.routes.common import last_fetched
from date_romania.api.schemas import PnrrStatus, Source
from date_romania.models import PnrrContract as Contract
from date_romania.models import PnrrContractLine as Line
from date_romania.models import PnrrEdition as Edition
from date_romania.models import PnrrMeasure as Measure
from date_romania.models import SourceDocument
from date_romania.personal_id import mask_cnp
from date_romania.sources import PNRR

# The dashboard's words for a contract's state, and ours.
STATUS: dict[str, PnrrStatus] = {
    "ÎN IMPLEMENTARE": "in_progress",
    "ÎN IMPLEMENTARE (SUB 30%)": "under_30",
    "FINALIZAT": "finished",
}
RAW_STATUS = {ours: theirs for theirs, ours in STATUS.items()}


def status(written: str | None) -> PnrrStatus | None:
    return STATUS.get(plain_status(written))


def plain_status(written: str | None) -> str:
    """The dashboard writes a status in either case: 'ÎN IMPLEMENTARE (sub 30%)'."""
    return (written or "").strip().upper()


def masked(value: str | None) -> str | None:
    return mask_cnp(value, checked=True)


def newest_edition(session: Session) -> Edition:
    edition = session.scalar(select(Edition).order_by(Edition.day.desc()).limit(1))
    if edition is None:
        raise HTTPException(404, "No PNRR edition collected yet")
    return edition


def edition_source(session: Session, edition: Edition) -> Source:
    """The dashboard edition behind every figure: its files, and when they were taken."""
    return Source(
        publisher=PNRR.publisher,
        record=PNRR.dataset,
        url=PNRR.list_url,
        fetched_at=last_fetched(session, PNRR),
        documents=session.scalar(
            select(func.count()).where(
                SourceDocument.source == PNRR.key,
                SourceDocument.url.contains(f"{edition.day:%Y%m%d}-"),
            )
        ),
    )


def per_contract():
    """Each contract's measures added up; its status and progress only where they agree."""
    return (
        select(
            Line.contract_id,
            func.sum(Line.total).label("total"),
            func.sum(Line.eu).label("eu"),
            func.count(func.upper(func.trim(Line.status)).distinct()).label("statuses"),
            func.min(Line.status).label("status"),
            func.count(Line.physical_progress.distinct()).label("physicals"),
            func.min(Line.physical_progress).label("physical"),
        )
        .group_by(Line.contract_id)
        .subquery()
    )


def find_measure(session: Session, code: str) -> Measure:
    found = session.scalar(select(Measure).where(func.lower(Measure.code) == code.lower()))
    if found is None:
        raise HTTPException(404, f"No PNRR measure {code}")
    return found


def on_measure(code: str):
    return Contract.id.in_(select(Line.contract_id).where(Line.measure_code == code))
