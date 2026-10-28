"""The Recovery and Resilience Plan: the programme and its measures. The contracts are in
pnrr_contracts.py, what both share in pnrr_common.py.

Natural persons never appear by name (Crispy, 22.10.2026): their contracts are left out of
every list and have no page; text is served with valid personal codes masked.
"""

from fastapi import APIRouter
from sqlalchemy import func, select

from date_romania.api.routes.common import Db, ref
from date_romania.api.routes.pnrr_common import (
    edition_source,
    find_measure,
    masked,
    newest_edition,
    on_measure,
)
from date_romania.api.schemas import (
    PnrrMeasure,
    PnrrProgramme,
    PnrrTopRecipient,
)
from date_romania.models import Entity
from date_romania.models import PnrrContract as Contract
from date_romania.models import PnrrContractLine as Line
from date_romania.models import PnrrMeasure as Measure
from date_romania.models import PnrrPayment as Payment
from date_romania.models import PnrrTopRecipient as Top

router = APIRouter(prefix="/programmes/pnrr", tags=["programmes"])


@router.get("")
def programme(session: Db) -> PnrrProgramme:
    """The plan from the newest dashboard edition held: its totals, its 143 measures and
    the largest final recipients."""
    edition = newest_edition(session)
    contracts = (
        select(Line.measure_code, func.count(Line.contract_id.distinct()).label("contracts"))
        .group_by(Line.measure_code)
        .subquery()
    )
    measures = session.execute(
        select(Measure, func.coalesce(contracts.c.contracts, 0))
        .outerjoin(contracts, contracts.c.measure_code == Measure.code)
        .order_by(Measure.code)
    ).all()
    top = session.execute(
        select(Top, Entity)
        .outerjoin(Entity, Entity.cui == Top.cui)
        .order_by(Top.total.desc().nulls_last(), Top.cui)
    ).all()
    return PnrrProgramme(
        edition=edition.day,
        allocated_eur=edition.allocated_eur,
        paid_eur=edition.paid_eur,
        received_eur=edition.received_eur,
        contracts=edition.contracts,
        beneficiaries_contracted=edition.beneficiaries_contracted,
        beneficiaries_paid=edition.beneficiaries_paid,
        contracted_ron=sum((m.contracted_eu_ron or 0) for m, _ in measures),
        measures=[_measure_row(m, count) for m, count in measures],
        top=[
            PnrrTopRecipient(
                cui=each.cui,
                name=masked(each.name),
                entity=ref(entity),
                received=each.total,
                last_received_on=each.last_received_on,
            )
            for each, entity in top
        ],
        source=edition_source(session, edition),
    )


def _measure_row(measure: Measure, contracts: int) -> dict:
    return {
        "code": measure.code,
        "component": measure.component,
        "name": measure.name,
        "ministry": measure.ministry,
        "funding": measure.funding,
        "allocated_eur": measure.allocated_eur,
        "contracted_ron": measure.contracted_eu_ron,
        "paid_ron": measure.paid_ron,
        "paid_eur": measure.paid_eur,
        "contracts": contracts,
    }


@router.get("/measures/{code}")
def measure(session: Db, code: str) -> PnrrMeasure:
    """One measure: its money, how much went to beneficiaries without a contract in the
    list, and how many of its contracts are natural persons'."""
    found = find_measure(session, code)
    contracts, natural = session.execute(
        select(func.count(), func.count().filter(Contract.natural_person)).where(
            on_measure(found.code)
        )
    ).one()
    paid, payments = session.execute(
        select(func.coalesce(func.sum(Payment.amount), 0), func.count()).where(
            Payment.measure_code == found.code, Payment.contracts_on_measure == 0
        )
    ).one()
    edition = newest_edition(session)
    return PnrrMeasure(
        **_measure_row(found, contracts),
        ministry_name=found.ministry_name,
        paid_without_contract=paid,
        payments_without_contract=payments,
        natural_persons=natural,
        counties=session.scalars(
            select(Contract.county)
            .where(on_measure(found.code), ~Contract.natural_person, Contract.county.is_not(None))
            .distinct()
            .order_by(Contract.county)
        ).all(),
        edition=edition.day,
        source=edition_source(session, edition),
    )
