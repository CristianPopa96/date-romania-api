"""The EU money of one beneficiary: its cohesion projects by programme and its PNRR
contracts and payments, for the institution, supplier and place pages.

The two kinds are never added together, nor are two programmes' figures: each describes
the day of its own list or edition.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania.api.routes.common import Db, ref
from date_romania.api.routes.eu_projects import lists_source
from date_romania.api.routes.pnrr import edition_source
from date_romania.api.schemas import (
    EuBeneficiaryFunds,
    EuBeneficiaryPnrr,
    EuBeneficiaryProgramme,
)
from date_romania.eu_links import PROBABLE
from date_romania.eu_programmes import PROGRAMMES
from date_romania.models import Entity
from date_romania.models import EuProject as Project
from date_romania.models import PnrrContract as Contract
from date_romania.models import PnrrContractLine as Line
from date_romania.models import PnrrEdition as Edition
from date_romania.models import PnrrPayment as Payment

router = APIRouter(prefix="/programmes/eu-beneficiaries", tags=["programmes"])


@router.get("/{cui}")
def beneficiary(session: Db, cui: int) -> EuBeneficiaryFunds:
    """What one beneficiary holds of both kinds of EU money. 404 when the CUI is not held."""
    entity = session.get(Entity, cui)
    if entity is None:
        raise HTTPException(404, "Entity not found")
    mine = Project.entity_cui == cui
    rows = {
        row.programme: row
        for row in session.execute(
            select(
                Project.programme,
                func.count().label("projects"),
                func.sum(Project.total_value).label("total"),
                func.sum(Project.paid).label("paid"),
                func.max(Project.cut_off).label("cut_off"),
                func.count().filter(Project.entity_confidence == PROBABLE).label("by_name"),
            )
            .where(mine)
            .group_by(Project.programme)
        )
    }
    cohesion = [
        EuBeneficiaryProgramme(
            code=each.code,
            name=each.name,
            period=each.period,
            projects=row.projects,
            total=row.total,
            paid=row.paid,
            cut_off=row.cut_off,
            by_name=row.by_name,
        )
        for each in PROGRAMMES
        if (row := rows.get(each.code))
    ]
    return EuBeneficiaryFunds(
        entity=ref(entity),
        cohesion=cohesion,
        cohesion_source=lists_source(session, mine) if cohesion else None,
        pnrr=_pnrr(session, cui),
    )


def _pnrr(session: Session, cui: int) -> EuBeneficiaryPnrr | None:
    edition = session.scalar(select(Edition).order_by(Edition.day.desc()).limit(1))
    if edition is None:
        return None
    contracts, total = session.execute(
        select(func.count(Contract.id.distinct()), func.sum(Line.total))
        .select_from(Contract)
        .outerjoin(Line, Line.contract_id == Contract.id)
        .where(Contract.beneficiary_cui == cui, ~Contract.natural_person)
    ).one()
    paid, payments, first_day, last_day = session.execute(
        select(
            func.coalesce(func.sum(Payment.amount), 0),
            func.count(),
            func.min(Payment.paid_on),
            func.max(Payment.paid_on),
        ).where(Payment.beneficiary_cui == cui, ~Payment.natural_person)
    ).one()
    if not contracts and not payments:
        return None
    return EuBeneficiaryPnrr(
        contracts=contracts,
        total=total,
        paid=paid,
        payments=payments,
        first_day=first_day,
        last_day=last_day,
        edition=edition.day,
        source=edition_source(session, edition),
    )
