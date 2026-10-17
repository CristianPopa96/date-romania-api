"""An institution's budget: for a town hall or a county council, its executed budget and
the Anghel Saligny payments to it."""

from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania import local_money
from date_romania.api.routes.common import Db, last_fetched, ref
from date_romania.api.schemas import (
    ChapterAmount,
    InstitutionBudget,
    LocalBudgetOut,
    PlaceRef,
    ProgrammePayments,
    RevenueAmount,
    Source,
)
from date_romania.models import Entity, Place, PniasPayment, SourceDocument
from date_romania.sources import LOCAL_BUDGETS, PNIAS_PAYMENTS

router = APIRouter()


def _budget(session: Session, siruta: int) -> LocalBudgetOut | None:
    found = local_money.budget(session, siruta)
    if found is None:
        return None
    doc = session.get(SourceDocument, found.document_id)
    return LocalBudgetOut(
        year=found.year,
        executed_on=date(found.year, 12, 31),
        revenue=found.revenue,
        revenue_lines=[
            RevenueAmount(line=line, amount=amount) for line, amount in found.revenue_lines.items()
        ],
        spending=found.spending,
        capital=found.capital,
        chapters=[
            ChapterAmount(chapter=chapter, amount=amount)
            for chapter, amount in sorted(found.chapters.items(), key=lambda each: -each[1])
            if amount
        ],
        source=Source(
            publisher=LOCAL_BUDGETS.publisher,
            record=f"MDLPA · Situația veniturilor și cheltuielilor {found.year}",
            url=LOCAL_BUDGETS.list_url,
            fetched_at=doc.fetched_at,
            document_id=doc.id,
            sha256=doc.sha256,
            parser_version=doc.parser_version,
        ),
    )


def _payments(session: Session, siruta: int) -> ProgrammePayments | None:
    payments, amount, projects, first, last, files = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(PniasPayment.amount), 0),
            func.count(PniasPayment.project_id.distinct()),
            func.min(PniasPayment.published_on),
            func.max(PniasPayment.published_on),
            func.count(PniasPayment.source_document_id.distinct()),
        ).where(PniasPayment.siruta == siruta)
    ).one()
    if not payments:
        return None
    return ProgrammePayments(
        amount=amount,
        payments=payments,
        projects=projects,
        first_published=first,
        last_published=last,
        source=Source(
            publisher=PNIAS_PAYMENTS.publisher,
            record=PNIAS_PAYMENTS.dataset,
            url=PNIAS_PAYMENTS.list_url,
            fetched_at=last_fetched(session, PNIAS_PAYMENTS),
            documents=files,
        ),
    )


@router.get("/institutions/{cui}/budget", tags=["entities"])
def institution_budget(session: Db, cui: int) -> InstitutionBudget:
    """For a town hall or a county council: the latest executed budget held and the
    Anghel Saligny payments to it. Every institution: the one that funds it."""
    entity = session.get(Entity, cui)
    if entity is None:
        raise HTTPException(404, f"No institution or company with CUI {cui}")
    place = session.scalar(select(Place).where(Place.town_hall_cui == cui))
    funder = session.get(Entity, entity.parent_cui) if entity.parent_cui else None
    return InstitutionBudget(
        place=place and PlaceRef(siruta=place.siruta, name=place.name, kind=place.kind),
        funder=ref(funder),
        budget=place and _budget(session, place.siruta),
        programme_payments=place and _payments(session, place.siruta),
    )
