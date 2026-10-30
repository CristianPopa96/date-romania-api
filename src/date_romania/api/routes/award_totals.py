"""Contracts added up: what an institution awarded, what a company won, and the rankings."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.api.routes.award_common import (
    EuFunded,
    Won,
    awards_source,
    in_period,
    notice_filters,
    period,
    won_filters,
)
from date_romania.api.routes.common import County, Cpv, Db, located_in
from date_romania.api.routes.rankings import Page, RankingPage, ranked
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
        period=period(session),
        **totals.model_dump(),
        source=awards_source(session, AwardNotice.buyer_cui == cui),
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
        source=awards_source(session, own),
    )


def _ranking(
    session: Session,
    side: ColumnElement,
    won: Won | None,
    filters: list[ColumnElement[bool]],
    page: Page,
    *joins,
) -> ContractRanking:
    contracts = func.count()
    query = select(Entity.cui, Entity.name, Entity.kind).add_columns(
        contracts.label("contracts"), money.contract_value.label("value")
    )
    query = query.select_from(AwardContract).join(
        AwardNotice, AwardContract.notice_id == AwardNotice.id
    )
    for target, on in joins:
        query = query.join(target, on)
    query = (
        query.join(Entity, Entity.cui == side)
        .where(*in_period(session), *won_filters(won), *filters)
        .group_by(Entity.cui)
    )
    column = contracts if page.sort == "count" else money.contract_value
    total, value, rows = ranked(session, query, column, page)
    return ContractRanking(
        period=period(session),
        won=won,
        total=total,
        value=value,
        items=[
            ContractRankingRow(
                rank=row.place,
                cui=row.cui,
                name=row.name,
                kind=row.kind,
                contracts=row.contracts,
                value=row.value,
            )
            for row in rows
        ],
        source=awards_source(session, *won_filters(won), *filters),
    )


@router.get("/rankings/contract-suppliers", tags=["rankings"])
def ranking_contract_suppliers(
    session: Db,
    page: RankingPage,
    won: Won = "alone",
    cpv: Cpv = None,
    eu_funded: EuFunded = None,
    county: County = None,
) -> ContractRanking:
    """Companies by the value of the contracts they won, alone or in associations.

    A contract won by an association appears at every member with its whole value.
    """
    # SEAP can list one company twice among the winners of a contract: count it once.
    members = select(AwardWinner.contract_id, AwardWinner.supplier_cui).distinct().subquery()
    winners = (members, members.c.contract_id == AwardContract.id)
    filters = notice_filters(cpv, eu_funded)
    if county:
        filters.append(located_in(members.c.supplier_cui, county))
    return _ranking(session, members.c.supplier_cui, won, filters, page, winners)


@router.get("/rankings/contract-institutions", tags=["rankings"])
def ranking_contract_institutions(
    session: Db,
    page: RankingPage,
    cpv: Cpv = None,
    eu_funded: EuFunded = None,
    county: County = None,
) -> ContractRanking:
    """Institutions by the value of the contracts they awarded, or by how many; each
    contract counted once."""
    filters = notice_filters(cpv, eu_funded)
    if county:
        filters.append(located_in(AwardNotice.buyer_cui, county))
    return _ranking(session, AwardNotice.buyer_cui, None, filters, page)
