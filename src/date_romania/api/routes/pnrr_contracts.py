"""The Recovery and Resilience Plan's financing contracts: the list, and one contract with
the payments that can be told to be its own.

Natural persons never appear by name (Crispy, 22.10.2026): their contracts are counted,
never listed, and have no page.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from date_romania.api.routes.common import Db, Limit, Offset, ref
from date_romania.api.routes.list_common import Order, ordered
from date_romania.api.routes.pnrr_common import (
    masked,
    newest_edition,
    on_measure,
    per_contract,
    plain_status,
    status,
)
from date_romania.api.routes.pnrr_contract_list import (
    CONTRACTS,
    LISTED,
    SUMS,
    PnrrContractFilters,
)
from date_romania.api.schemas import (
    PnrrContract,
    PnrrContractPage,
    PnrrContractRow,
    PnrrLine,
    PnrrPayment,
    PnrrPayments,
    PnrrSibling,
    Source,
)
from date_romania.models import Entity, SourceDocument
from date_romania.models import PnrrContract as Contract
from date_romania.models import PnrrContractLine as Line
from date_romania.models import PnrrMeasure as Measure
from date_romania.models import PnrrPayment as Payment
from date_romania.sources import PNRR

router = APIRouter(prefix="/programmes/pnrr", tags=["programmes"])


@router.get("/contracts")
def contracts(
    session: Db,
    filters: PnrrContractFilters,
    sort: Annotated[
        Literal["value", "progress"],
        Query(description="The value, or the physical progress its measures agree on."),
    ] = "value",
    order: Order = "desc",
    limit: Limit = 20,
    offset: Offset = 0,
) -> PnrrContractPage:
    """Financing contracts under the filters given, the largest first, or in any column's
    order. Natural persons' are counted, never listed."""
    conditions = filters.all()
    total, natural = session.execute(
        select(func.count().filter(LISTED), func.count().filter(Contract.natural_person))
        .select_from(CONTRACTS)
        .where(*conditions)
    ).one()
    column = SUMS.c.physical if sort == "progress" else SUMS.c.total
    rows = session.execute(
        ordered(_rows().where(LISTED, *conditions), column, order, Contract.id)
        .limit(limit)
        .offset(offset)
    )
    return PnrrContractPage(
        total=total,
        natural_persons=natural,
        items=[
            PnrrContractRow(
                id=contract.id,
                number=contract.number,
                title=masked(contract.title),
                beneficiary=ref(entity),
                beneficiary_name=masked(contract.beneficiary_name),
                county=contract.county,
                total=row.total,
                status=status(row.status) if row.statuses == 1 else None,
                physical_progress=row.physical if row.physicals == 1 else None,
                # Zero distinct values is a value nobody published, not a disagreement.
                measures_differ=row.statuses > 1 or row.physicals > 1,
            )
            for row in rows
            for contract, entity in [(row[0], row[1])]
        ],
    )


def _rows() -> Select:
    return select(
        Contract,
        Entity,
        SUMS.c.total,
        SUMS.c.statuses,
        SUMS.c.status,
        SUMS.c.physicals,
        SUMS.c.physical,
    ).select_from(CONTRACTS.outerjoin(Entity, Entity.cui == Contract.beneficiary_cui))


@router.get("/contracts/{contract_id}")
def contract(session: Db, contract_id: int) -> PnrrContract:
    """One financing contract: its measures, and for each the payments to the beneficiary,
    which are the contract's own only when it is the beneficiary's one contract there."""
    found = session.get(Contract, contract_id)
    if found is None or found.natural_person:
        raise HTTPException(404, f"No PNRR contract {contract_id}")
    lines = session.execute(
        select(Line, Measure.name)
        .join(Measure, Measure.code == Line.measure_code)
        .where(Line.contract_id == found.id)
        .order_by(Line.position)
    ).all()
    doc = session.get(SourceDocument, found.source_document_id)
    edition = newest_edition(session)
    statuses = {plain_status(line.status) for line, _ in lines if line.status}
    # A blank figure is one nobody published, as in the list: never a disagreement.
    physical = {line.physical_progress for line, _ in lines if line.physical_progress is not None}
    financial = {
        line.financial_progress for line, _ in lines if line.financial_progress is not None
    }
    differ = len(statuses) > 1 or len(physical) > 1 or len(financial) > 1
    return PnrrContract(
        id=found.id,
        number=found.number,
        title=masked(found.title),
        beneficiary=ref(
            session.get(Entity, found.beneficiary_cui) if found.beneficiary_cui else None
        ),
        ministry=found.ministry,
        ministry_name=session.scalar(
            select(Measure.ministry_name).where(Measure.code == lines[0][0].measure_code)
        )
        if lines
        else None,
        signed_on=found.signed_on,
        starts_on=found.starts_on,
        county=found.county,
        locality=found.locality,
        total=sum((line.total or 0) for line, _ in lines),
        eu=sum((line.eu or 0) for line, _ in lines),
        status=status(next(iter(statuses))) if len(statuses) == 1 else None,
        ends_on=max((line.ends_on for line, _ in lines if line.ends_on), default=None),
        physical_progress=None if differ else next(iter(physical), None),
        financial_progress=None if differ else next(iter(financial), None),
        measures_differ=differ,
        lines=[
            PnrrLine(
                measure=line.measure_code,
                measure_name=name,
                funding=line.funding,
                total=line.total,
                eu=line.eu,
                status=status(line.status),
                ends_on=line.ends_on,
                physical_progress=line.physical_progress,
                financial_progress=line.financial_progress,
            )
            for line, name in lines
        ],
        payments=[
            _payments(session, found, code)
            for code in dict.fromkeys(line.measure_code for line, _ in lines)
        ],
        edition=edition.day,
        source=Source(
            publisher=PNRR.publisher,
            record=PNRR.dataset,
            url=PNRR.list_url,
            fetched_at=doc.fetched_at,
            document_id=doc.id,
            sha256=doc.sha256,
            parser_version=found.parser_version,
        ),
    )


def _payments(session: Session, contract: Contract, code: str) -> PnrrPayments:
    """The payments to the beneficiary on one measure, and its contracts there."""
    if contract.beneficiary_cui is None:
        return PnrrPayments(
            measure=code,
            contracts=1,
            paid=0,
            count=0,
            first_day=None,
            last_day=None,
            items=[],
            others=[],
        )
    paid = session.scalars(
        select(Payment)
        .where(Payment.beneficiary_cui == contract.beneficiary_cui, Payment.measure_code == code)
        .order_by(Payment.paid_on.desc().nulls_last(), Payment.position)
    ).all()
    sums = per_contract()
    siblings = session.execute(
        select(Contract, sums.c.total)
        .join(sums, sums.c.contract_id == Contract.id)
        .where(Contract.beneficiary_cui == contract.beneficiary_cui, on_measure(code))
        .order_by(sums.c.total.desc().nulls_last(), Contract.id)
    ).all()
    days = [p.paid_on for p in paid if p.paid_on]
    return PnrrPayments(
        measure=code,
        contracts=len(siblings),
        paid=sum(p.amount for p in paid),
        count=len(paid),
        first_day=min(days, default=None),
        last_day=max(days, default=None),
        items=[PnrrPayment(paid_on=p.paid_on, amount=p.amount, funding=p.funding) for p in paid],
        others=[
            PnrrSibling(id=other.id, number=other.number, title=masked(other.title), total=total)
            for other, total in siblings
            if other.id != contract.id
        ]
        if len(siblings) > 1
        else [],
    )
