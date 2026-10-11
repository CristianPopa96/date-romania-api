"""Contracts added up: what an institution awarded, what a company won, and the rankings."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.api.routes.awards import Won, awards_source, in_period, period, won_filters
from date_romania.api.routes.common import Db, Limit, ref
from date_romania.api.schemas import (
    ContractRanking,
    ContractRankingRow,
    ContractTotals,
    InstitutionContracts,
    SupplierContracts,
)
from date_romania.models import AwardContract, AwardNotice, AwardWinner, Entity

router = APIRouter()


def _totals(session: Session, *filters: ColumnElement[bool]) -> ContractTotals:
    contracts, value = session.execute(
        select(func.count(), money.contract_value)
        .select_from(AwardContract)
        .join(AwardNotice, AwardContract.notice_id == AwardNotice.id)
        .where(*in_period(session), *filters)
    ).one()
    return ContractTotals(contracts=contracts, value=value)


def _entity(session: Session, cui: int) -> None:
    if session.get(Entity, cui) is None:
        raise HTTPException(404, f"No institution or company with CUI {cui}")


@router.get("/institutions/{cui}/contracts", tags=["entities"])
def institution_contracts(session: Db, cui: int) -> InstitutionContracts:
    """What an institution awarded in the period we hold. Each contract is counted once."""
    _entity(session, cui)
    totals = _totals(session, AwardNotice.buyer_cui == cui)
    return InstitutionContracts(
        period=period(session), **totals.model_dump(), source=awards_source(session)
    )


@router.get("/suppliers/{cui}/contracts", tags=["entities"])
def supplier_contracts(session: Db, cui: int) -> SupplierContracts:
    """What a company won in the period we hold, alone and in associations.

    SEAP gives one value for a contract won by an association and does not split it between
    the members, so `association` carries the whole value of those contracts. The two
    figures must never be added.
    """
    _entity(session, cui)
    own = (
        select(AwardWinner.contract_id)
        .where(AwardWinner.contract_id == AwardContract.id, AwardWinner.supplier_cui == cui)
        .exists()
    )
    return SupplierContracts(
        period=period(session),
        alone=_totals(session, own, ~money.is_association),
        association=_totals(session, own, money.is_association),
        source=awards_source(session),
    )


def _ranking(
    session: Session, side: ColumnElement, won: Won | None, limit: int, *joins
) -> ContractRanking:
    query = select(Entity, func.count().label("contracts"), money.contract_value.label("value"))
    query = query.select_from(AwardContract).join(
        AwardNotice, AwardContract.notice_id == AwardNotice.id
    )
    for target, on in joins:
        query = query.join(target, on)
    rows = session.execute(
        query.join(Entity, Entity.cui == side)
        .where(*in_period(session), *won_filters(won))
        .group_by(Entity.cui)
        .order_by(money.contract_value.desc(), Entity.cui)
        .limit(limit)
    )
    return ContractRanking(
        period=period(session),
        won=won,
        items=[
            ContractRankingRow(
                rank=rank, **ref(entity).model_dump(), contracts=contracts, value=value
            )
            for rank, (entity, contracts, value) in enumerate(rows, 1)
        ],
        source=awards_source(session),
    )


@router.get("/rankings/contract-suppliers", tags=["rankings"])
def ranking_contract_suppliers(
    session: Db, won: Won = "alone", limit: Limit = 20
) -> ContractRanking:
    """Companies by the value of the contracts they won, alone or in associations.

    A contract won by an association appears at every member with its whole value.
    """
    winners = (AwardWinner, AwardWinner.contract_id == AwardContract.id)
    return _ranking(session, AwardWinner.supplier_cui, won, limit, winners)


@router.get("/rankings/contract-institutions", tags=["rankings"])
def ranking_contract_institutions(session: Db, limit: Limit = 20) -> ContractRanking:
    """Institutions by the value of the contracts they awarded; each contract counted once."""
    return _ranking(session, AwardNotice.buyer_cui, None, limit)
