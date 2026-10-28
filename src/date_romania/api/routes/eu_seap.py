"""The SEAP records tied to an EU project: the contracts of the award notices and the direct
purchases whose text cites a cohesion project's SMIS code or a PNRR contract's number (see
`eu_seap_links.py`). One answer for both kinds of project."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.api.routes import award_common
from date_romania.api.routes.common import Db, Limit, Offset
from date_romania.api.routes.purchases import purchase_row, purchases_query
from date_romania.api.schemas import EuSeapContract, EuSeapLinks, EuSeapPurchase
from date_romania.models import AwardContract, DirectPurchase, EuProject, EuSeapLink, PnrrContract

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

    return EuSeapLinks(
        contracts_total=session.scalar(select(func.count()).select_from(AwardContract).where(*tied))
        or 0,
        contracts=[
            EuSeapContract(contract=contract, **link(notices[contract.notice_id]))
            for contract in contracts
        ],
        purchases=[
            EuSeapPurchase(purchase=purchase, **link(purchases[purchase.id]))
            for purchase in map(purchase_row, bought)
        ],
    )


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
