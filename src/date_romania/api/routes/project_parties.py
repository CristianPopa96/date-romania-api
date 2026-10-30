"""The projects of one institution or company (design D22, step 3): those it is the
beneficiary of, those it was paid through, and the programmes they come from.

A company is paid through a project as the builder an Anghel Saligny payment file names
(published), or as the winner of a SEAP notice, or the supplier of a direct purchase, whose
text cites the project (`eu_seap_link`, probable). `/projects/programmes` gives a
beneficiary's projects by programme, each with its figures as its programme publishes them.
"""

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, and_, func, or_, select, union
from sqlalchemy.orm import Session

from date_romania import eu_programmes
from date_romania.api.routes.common import Db
from date_romania.api.schemas.projects import ProgrammeFigures, ProjectProgrammes
from date_romania.models import (
    AwardContract,
    AwardWinner,
    DirectPurchase,
    EuProject,
    EuSeapLink,
    PniasPayment,
    PnrrEdition,
    PnrrPayment,
    Project,
)
from date_romania.projects import AS, COHESION, PNRR

router = APIRouter(prefix="/projects", tags=["projects"])

Via = Literal["beneficiary", "builder", "notice", "purchase"]
# Natural persons are never listed by name.
LISTED = ~Project.natural_person


def programme_name(programme: str) -> tuple[str, str | None]:
    """A programme's name and period, from its code in the `project` table."""
    if programme == "AS":
        return "Anghel Saligny", None
    if programme == "PNRR":
        return "PNRR", None
    held = eu_programmes.BY_CODE.get(programme)
    return (held.name, held.period) if held else (programme, None)


def _built(cui: int):
    return select(PniasPayment.project_id).where(PniasPayment.builder_cui == cui)


def _won(column, cui: int):
    """The projects (`column` of `eu_seap_link`) whose tied notices the company won."""
    return (
        select(column)
        .join(AwardContract, AwardContract.notice_id == EuSeapLink.notice_id)
        .join(AwardWinner, AwardWinner.contract_id == AwardContract.id)
        .where(column.is_not(None), AwardWinner.supplier_cui == cui)
    )


def _sold(column, cui: int):
    """The projects whose tied direct purchases the company sold."""
    return (
        select(column)
        .join(DirectPurchase, DirectPurchase.id == EuSeapLink.purchase_id)
        .where(column.is_not(None), DirectPurchase.supplier_cui == cui)
    )


def company_condition(cui: int) -> ColumnElement[bool]:
    """The projects a company is the beneficiary of or was paid through."""
    return or_(
        Project.beneficiary_cui == cui,
        and_(Project.kind == AS, Project.key.in_(_built(cui))),
        and_(
            Project.kind == COHESION,
            Project.key.in_(union(_won(EuSeapLink.smis, cui), _sold(EuSeapLink.smis, cui))),
        ),
        and_(
            Project.kind == PNRR,
            Project.key.in_(
                union(
                    _won(EuSeapLink.pnrr_contract_id, cui),
                    _sold(EuSeapLink.pnrr_contract_id, cui),
                )
            ),
        ),
    )


def vias(session: Session, cui: int, rows: list[Project]) -> dict[int, Via]:
    """How the company is tied to each project of a page, by the project's row id: the
    beneficiary first, then the payment file, then a notice won, then a purchase sold."""
    built = set(session.scalars(_built(cui)))
    won = {
        COHESION: set(session.scalars(_won(EuSeapLink.smis, cui))),
        PNRR: set(session.scalars(_won(EuSeapLink.pnrr_contract_id, cui))),
    }
    sold = {
        COHESION: set(session.scalars(_sold(EuSeapLink.smis, cui))),
        PNRR: set(session.scalars(_sold(EuSeapLink.pnrr_contract_id, cui))),
    }
    found: dict[int, Via] = {}
    for row in rows:
        if row.beneficiary_cui == cui:
            found[row.id] = "beneficiary"
        elif row.kind == AS and row.key in built:
            found[row.id] = "builder"
        elif row.key in won.get(row.kind, ()):
            found[row.id] = "notice"
        elif row.key in sold.get(row.kind, ()):
            found[row.id] = "purchase"
    return found


@router.get("/programmes")
def project_programmes(
    session: Db,
    beneficiary: Annotated[int, Query(description="The beneficiary's CUI.")],
) -> ProjectProgrammes:
    """A beneficiary's projects by programme, each with its count, its value and what was
    paid as the programme publishes it, at its own day: never added across programmes.
    PNRR payments name the beneficiary and the measure, so their sum is the beneficiary's,
    over every measure, never a contract's."""
    rows = session.execute(
        select(Project.kind, Project.programme, func.count(), func.sum(Project.value))
        .where(LISTED, Project.beneficiary_cui == beneficiary)
        .group_by(Project.kind, Project.programme)
        .order_by(func.count().desc(), Project.programme)
    ).all()
    figures = []
    for kind, programme, count, value in rows:
        paid, day, paid_as = _paid(session, kind, programme, beneficiary)
        name, period = programme_name(programme)
        figures.append(
            ProgrammeFigures(
                kind=kind,
                programme=programme,
                name=name,
                period=period,
                projects=count,
                value=value,
                paid=paid,
                paid_as=paid_as,
                day=day,
            )
        )
    return ProjectProgrammes(items=figures)


def _paid(session: Session, kind: str, programme: str, cui: int):
    """What was paid for a beneficiary's projects of one programme, its day, and how the
    programme publishes it."""
    if kind == AS:
        keys = select(Project.key).where(Project.kind == AS, Project.beneficiary_cui == cui)
        paid, day = session.execute(
            select(func.sum(PniasPayment.amount), func.max(PniasPayment.published_on)).where(
                PniasPayment.project_id.in_(keys)
            )
        ).one()
        return paid or Decimal(0), day, "files"
    if kind == PNRR:
        paid = session.scalar(
            select(func.sum(PnrrPayment.amount)).where(PnrrPayment.beneficiary_cui == cui)
        )
        day = session.scalar(select(func.max(PnrrEdition.day)))
        return paid or Decimal(0), day, "beneficiary"
    paid, day = session.execute(
        select(func.sum(EuProject.paid), func.max(EuProject.cut_off)).where(
            EuProject.entity_cui == cui, EuProject.programme == programme
        )
    ).one()
    return paid, day, "cumulative"
