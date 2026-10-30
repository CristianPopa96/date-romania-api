"""The SEAP records tied to an EU project: the contracts of the award notices and the direct
purchases whose text cites a cohesion project's SMIS code or a PNRR contract's number (see
`eu_seap_links.py`). One answer for both kinds of project."""

from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.api.routes import award_common
from date_romania.api.routes.common import Db, Limit, Offset, ref
from date_romania.api.routes.purchases import purchase_row, purchases_query
from date_romania.api.schemas import EuSeapContract, EuSeapLinks, EuSeapPurchase
from date_romania.api.schemas.eu_projects import SeapCompany
from date_romania.models import (
    AwardContract,
    AwardWinner,
    DirectPurchase,
    Entity,
    EuProject,
    EuSeapLink,
    PnrrContract,
)
from date_romania.text import plain

router = APIRouter(tags=["programmes"])


def _links(session: Session, project: ColumnElement[bool], limit: int, offset: int) -> EuSeapLinks:
    found = session.scalars(select(EuSeapLink).where(project)).all()
    notices = {link.notice_id: link for link in found if link.notice_id}
    purchases = {link.purchase_id: link for link in found if link.purchase_id}
    tied = [AwardContract.notice_id.in_(notices), money.contract_in_force]
    contracts = award_common.rows(
        session,
        award_common.contracts()
        .where(*tied)
        .order_by(AwardContract.contract_date.desc().nulls_last(), AwardContract.id)
        .limit(limit)
        .offset(offset),
    )
    bought = session.execute(
        purchases_query()
        .where(DirectPurchase.id.in_(purchases))
        .order_by(DirectPurchase.finalized_at.desc().nulls_last(), DirectPurchase.id)
    )

    def link(each: EuSeapLink) -> dict:
        return {"cited": each.cited, "method": each.method, "confidence": each.confidence}

    bought = list(map(purchase_row, bought))
    companies = _companies(session, tied, bought)
    return EuSeapLinks(
        notices=session.scalar(select(func.count(AwardContract.notice_id.distinct())).where(*tied))
        or 0,
        companies=len(companies),
        largest=max(companies.values(), key=lambda each: each[1])[0] if companies else None,
        contracts_total=session.scalar(select(func.count()).select_from(AwardContract).where(*tied))
        or 0,
        contracts=[
            EuSeapContract(contract=contract, **link(notices[contract.notice_id]))
            for contract in contracts
        ],
        purchases=[
            EuSeapPurchase(purchase=purchase, **link(purchases[purchase.id])) for purchase in bought
        ],
    )


def _companies(session: Session, tied, bought) -> dict[object, tuple[SeapCompany, Decimal]]:
    """Every company of the tied records, by CUI or by name where SEAP gives none, with the
    value of what it won and sold: contracts counted (never a framework agreement, a
    ceiling), each member of an association with the whole value, and accepted purchases."""
    names: dict[object, str] = {}
    cuis: dict[object, int | None] = {}
    values: dict[object, Decimal] = defaultdict(Decimal)
    rows = session.execute(
        select(
            AwardWinner.supplier_cui,
            AwardWinner.supplier_text,
            Entity.name,
            AwardContract.value_ron,
            money.contract_counted,
        )
        .join(AwardContract, AwardContract.id == AwardWinner.contract_id)
        .outerjoin(Entity, Entity.cui == AwardWinner.supplier_cui)
        .where(*tied)
    )
    for cui, text, name, value, counted in rows:
        key = cui or plain(text)
        names.setdefault(key, name or text or "")
        cuis[key] = cui
        if counted and value is not None:
            values[key] += value
    for purchase in bought:
        cui = purchase.supplier.cui if purchase.supplier else None
        key = cui or plain(purchase.supplier_text)
        if not key:
            continue
        names.setdefault(
            key, purchase.supplier.name if purchase.supplier else purchase.supplier_text
        )
        cuis[key] = cui
        if purchase.state_id == money.DIRECT_PURCHASE_ACCEPTED and purchase.value is not None:
            values[key] += Decimal(str(purchase.value))
    entities = {
        entity.cui: entity
        for entity in session.scalars(
            select(Entity).where(Entity.cui.in_([cui for cui in cuis.values() if cui]))
        )
    }
    return {
        key: (
            SeapCompany(name=names[key], entity=ref(entities.get(cuis[key]))),
            values[key],
        )
        for key in names
        if key
    }


@router.get("/programmes/eu-funds/projects/{smis}/seap")
def eu_project_seap(session: Db, smis: int, limit: Limit = 20, offset: Offset = 0) -> EuSeapLinks:
    """The SEAP contracts (`limit` and `offset` page them) and direct purchases whose text
    cites the project's SMIS code."""
    if session.get(EuProject, smis) is None:
        raise HTTPException(404, f"No EU project with SMIS {smis}")
    return _links(session, EuSeapLink.smis == smis, limit, offset)


@router.get("/programmes/pnrr/contracts/{contract_id}/seap")
def pnrr_contract_seap(
    session: Db, contract_id: int, limit: Limit = 20, offset: Offset = 0
) -> EuSeapLinks:
    """The SEAP contracts and direct purchases of the beneficiary whose text cites the
    contract's number."""
    found = session.get(PnrrContract, contract_id)
    if found is None or found.natural_person:
        raise HTTPException(404, f"No PNRR contract {contract_id}")
    return _links(session, EuSeapLink.pnrr_contract_id == contract_id, limit, offset)
