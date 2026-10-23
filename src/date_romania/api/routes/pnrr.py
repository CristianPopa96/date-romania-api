"""The Recovery and Resilience Plan: the programme and its measures, the contracts, one
contract with the payments that can be told to be its own.

Natural persons never appear by name (Crispy, 22.10.2026): their contracts are left out of
every list and have no page; text is served with valid personal codes masked.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from date_romania.api.routes.common import Db, Limit, Offset, containing, last_fetched, ref
from date_romania.api.schemas import (
    PnrrContract,
    PnrrContractPage,
    PnrrContractRow,
    PnrrLine,
    PnrrMeasure,
    PnrrPayment,
    PnrrPayments,
    PnrrProgramme,
    PnrrSibling,
    PnrrStatus,
    PnrrTopRecipient,
    Source,
)
from date_romania.models import Entity, SourceDocument, search_text
from date_romania.models import PnrrContract as Contract
from date_romania.models import PnrrContractLine as Line
from date_romania.models import PnrrEdition as Edition
from date_romania.models import PnrrMeasure as Measure
from date_romania.models import PnrrPayment as Payment
from date_romania.models import PnrrTopRecipient as Top
from date_romania.personal_id import mask_cnp
from date_romania.sources import PNRR

router = APIRouter(prefix="/programmes/pnrr", tags=["programmes"])

# The dashboard's words for a contract's state, and ours.
_STATUS: dict[str, PnrrStatus] = {
    "ÎN IMPLEMENTARE": "in_progress",
    "ÎN IMPLEMENTARE (SUB 30%)": "under_30",
    "FINALIZAT": "finished",
}
_RAW_STATUS = {ours: theirs for theirs, ours in _STATUS.items()}


def status(written: str | None) -> PnrrStatus | None:
    return _STATUS.get(_plain_status(written))


def _plain_status(written: str | None) -> str:
    """The dashboard writes a status in either case: 'ÎN IMPLEMENTARE (sub 30%)'."""
    return (written or "").strip().upper()


def _text(value: str | None) -> str | None:
    return mask_cnp(value, checked=True)


def _edition(session: Session) -> Edition:
    edition = session.scalar(select(Edition).order_by(Edition.day.desc()).limit(1))
    if edition is None:
        raise HTTPException(404, "No PNRR edition collected yet")
    return edition


def _source(session: Session, edition: Edition) -> Source:
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


def _per_contract():
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


@router.get("")
def programme(session: Db) -> PnrrProgramme:
    """The plan from the newest dashboard edition held: its totals, its 143 measures and
    the largest final recipients."""
    edition = _edition(session)
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
                name=_text(each.name),
                entity=ref(entity),
                received=each.total,
                last_received_on=each.last_received_on,
            )
            for each, entity in top
        ],
        source=_source(session, edition),
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


def _measure(session: Session, code: str) -> Measure:
    found = session.scalar(select(Measure).where(func.lower(Measure.code) == code.lower()))
    if found is None:
        raise HTTPException(404, f"No PNRR measure {code}")
    return found


def _on_measure(code: str):
    return Contract.id.in_(select(Line.contract_id).where(Line.measure_code == code))


@router.get("/measures/{code}")
def measure(session: Db, code: str) -> PnrrMeasure:
    """One measure: its money, how much went to beneficiaries without a contract in the
    list, and how many of its contracts are natural persons'."""
    found = _measure(session, code)
    contracts, natural = session.execute(
        select(func.count(), func.count().filter(Contract.natural_person)).where(
            _on_measure(found.code)
        )
    ).one()
    paid, payments = session.execute(
        select(func.coalesce(func.sum(Payment.amount), 0), func.count()).where(
            Payment.measure_code == found.code, Payment.contracts_on_measure == 0
        )
    ).one()
    edition = _edition(session)
    return PnrrMeasure(
        **_measure_row(found, contracts),
        ministry_name=found.ministry_name,
        paid_without_contract=paid,
        payments_without_contract=payments,
        natural_persons=natural,
        counties=session.scalars(
            select(Contract.county)
            .where(_on_measure(found.code), ~Contract.natural_person, Contract.county.is_not(None))
            .distinct()
            .order_by(Contract.county)
        ).all(),
        edition=edition.day,
        source=_source(session, edition),
    )


@router.get("/contracts")
def contracts(
    session: Db,
    measure: Annotated[str | None, Query(description="A measure code, e.g. 'C10.I3'.")] = None,
    county: Annotated[str | None, Query(description="As the dashboard writes it.")] = None,
    status_: Annotated[PnrrStatus | None, Query(alias="status")] = None,
    beneficiary: Annotated[int | None, Query(description="The beneficiary's CUI.")] = None,
    q: Annotated[
        str | None,
        Query(min_length=2, max_length=100, description="Part of the title or beneficiary."),
    ] = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> PnrrContractPage:
    """Financing contracts, the largest first. Natural persons' are counted, never listed."""
    filters = []
    if measure:
        filters.append(_on_measure(_measure(session, measure).code))
    if county:
        filters.append(Contract.county == county)
    if beneficiary is not None:
        filters.append(Contract.beneficiary_cui == beneficiary)
    if status_:
        filters.append(
            Contract.id.in_(
                select(Line.contract_id).where(
                    func.upper(func.trim(Line.status)) == _RAW_STATUS[status_]
                )
            )
        )
    if q:
        like = containing(q)
        filters.append(
            search_text(Contract.title).like(like)
            | search_text(Contract.beneficiary_name).like(like)
        )
    total, natural = session.execute(
        select(
            func.count().filter(~Contract.natural_person),
            func.count().filter(Contract.natural_person),
        )
        .select_from(Contract)
        .where(*filters)
    ).one()
    sums = _per_contract()
    rows = session.execute(
        _rows(sums)
        .where(*filters, ~Contract.natural_person)
        .order_by(sums.c.total.desc().nulls_last(), Contract.id)
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
                title=_text(contract.title),
                beneficiary=ref(entity),
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


def _rows(sums) -> Select:
    return (
        select(
            Contract,
            Entity,
            sums.c.total,
            sums.c.statuses,
            sums.c.status,
            sums.c.physicals,
            sums.c.physical,
        )
        .join(sums, sums.c.contract_id == Contract.id)
        .outerjoin(Entity, Entity.cui == Contract.beneficiary_cui)
    )


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
    edition = _edition(session)
    statuses = {_plain_status(line.status) for line, _ in lines if line.status}
    physical = {line.physical_progress for line, _ in lines}
    financial = {line.financial_progress for line, _ in lines}
    differ = len(statuses) > 1 or len(physical) > 1 or len(financial) > 1
    return PnrrContract(
        id=found.id,
        number=found.number,
        title=_text(found.title),
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
        physical_progress=None if differ or not lines else lines[0][0].physical_progress,
        financial_progress=None if differ or not lines else lines[0][0].financial_progress,
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
    sums = _per_contract()
    siblings = session.execute(
        select(Contract, sums.c.total)
        .join(sums, sums.c.contract_id == Contract.id)
        .where(Contract.beneficiary_cui == contract.beneficiary_cui, _on_measure(code))
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
            PnrrSibling(id=other.id, number=other.number, title=_text(other.title), total=total)
            for other, total in siblings
            if other.id != contract.id
        ]
        if len(siblings) > 1
        else [],
    )
