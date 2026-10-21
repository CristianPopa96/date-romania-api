"""Award notices and their contracts: one notice, and contracts by buyer or winner."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from date_romania import money
from date_romania.api.routes.award_common import (
    Buyer,
    EuFunded,
    Won,
    contracts,
    in_period,
    notice_filters,
    notice_url,
    period,
    rows,
    won_filters,
)
from date_romania.api.routes.award_csv import contracts_csv
from date_romania.api.routes.common import Cpv, Db, Format, Limit, Offset, record_source, ref
from date_romania.api.schemas import AwardNoticeOut, Contract, ContractPage, NoticeDetail
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardNoticeDetail,
    AwardNoticeVersion,
    AwardWinner,
    SourceDocument,
)
from date_romania.sources import SEAP_AWARDS

router = APIRouter(tags=["award notices"])

# A CSV file holds a whole list, not a page of it; it is read this many rows at a time.
CSV_BATCH = 1000


@router.get("/award-notices/{notice_id}")
def award_notice(session: Db, notice_id: int) -> AwardNoticeOut:
    """One award notice, by SEAP's own id, in the version in force when it was collected."""
    row = session.execute(
        select(AwardNotice, Buyer, SourceDocument.fetched_at, SourceDocument.sha256)
        .outerjoin(Buyer, AwardNotice.buyer_cui == Buyer.cui)
        .join(SourceDocument, AwardNotice.source_document_id == SourceDocument.id)
        .where(AwardNotice.id == notice_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(404, f"No award notice with id {notice_id}")
    notice, buyer, fetched_at, sha256 = row
    versions, first_published = session.execute(
        select(func.count(), func.min(AwardNoticeVersion.published_at)).where(
            AwardNoticeVersion.notice_id == notice_id
        )
    ).one()
    replaced_by = session.scalar(
        select(money.replaced.c.replaced_by)
        .join(AwardNotice, AwardNotice.id == money.replaced.c.replaced_by)
        .where(money.replaced.c.notice_id == notice_id)
        .order_by(AwardNotice.published_at.desc(), AwardNotice.id.desc())
        .limit(1)
    )
    detail = session.get(AwardNoticeDetail, notice_id)
    kinds = dict(
        session.execute(
            select(AwardContract.kind, func.count())
            .where(AwardContract.notice_id == notice_id)
            .group_by(AwardContract.kind)
        ).all()
    )
    total = session.scalar(
        select(money.contract_value).where(
            AwardContract.notice_id == notice_id, money.contract_counted
        )
    )
    return AwardNoticeOut(
        id=notice.id,
        notice_no=notice.notice_no,
        notice_type_id=notice.notice_type_id,
        title=notice.title,
        buyer=ref(buyer),
        buyer_text=notice.buyer_text,
        cpv_code=notice.cpv_code,
        cpv_name=notice.cpv_name,
        contract_type=notice.contract_type,
        procedure_type=notice.procedure_type,
        published_at=notice.published_at,
        first_published_at=first_published,
        versions=versions or None,
        replaced_by=replaced_by,
        detail=detail and NoticeDetail.model_validate(detail),
        contracts=sum(kinds.values()),
        ordinary=kinds.get(money.AWARD_CONTRACT, 0),
        frameworks=kinds.get(money.AWARD_FRAMEWORK, 0),
        subsequent=kinds.get(money.AWARD_SUBSEQUENT, 0),
        total=total,
        source=record_source(
            SEAP_AWARDS,
            notice,
            record=notice.notice_no,
            url=notice_url(notice),
            fetched_at=fetched_at,
            sha256=sha256,
        ),
    )


@router.get("/award-notices/{notice_id}/contracts")
def award_notice_contracts(
    session: Db, notice_id: int, limit: Limit = 50, offset: Offset = 0
) -> ContractPage:
    """Every contract of one notice, whatever its date, in SEAP's order of signing."""
    if session.get(AwardNotice, notice_id) is None:
        raise HTTPException(404, f"No award notice with id {notice_id}")
    own = AwardContract.notice_id == notice_id
    total = session.scalar(select(func.count()).select_from(AwardContract).where(own))
    query = (
        contracts()
        .where(own)
        .order_by(AwardContract.contract_date.nulls_last(), AwardContract.id)
        .limit(limit)
        .offset(offset)
    )
    return ContractPage(total=total, period=None, items=rows(session, query))


@router.get("/award-contracts")
def award_contracts(
    session: Db,
    buyer: Annotated[int | None, Query(description="CUI of the buying institution.")] = None,
    supplier: Annotated[int | None, Query(description="CUI of a winner.")] = None,
    won: Annotated[
        Won | None, Query(description="By one company, or by an association of several.")
    ] = None,
    cpv: Cpv = None,
    eu_funded: EuFunded = None,
    sort: Literal["newest", "value"] = "newest",
    limit: Limit = 20,
    offset: Offset = 0,
    format: Format = "json",
) -> ContractPage:
    """Contracts signed in the period we hold, newest or largest first.

    Framework agreements are left out: their value is a ceiling, and what is committed
    under them are their subsequent contracts, which are listed. The list is not complete:
    SEAP publishes many contracts weeks after they are signed.
    """
    filters = [*in_period(session), *won_filters(won), *notice_filters(cpv, eu_funded)]
    if buyer is not None:
        filters.append(AwardNotice.buyer_cui == buyer)
    if supplier is not None:
        filters.append(
            select(AwardWinner.contract_id)
            .where(
                AwardWinner.contract_id == AwardContract.id, AwardWinner.supplier_cui == supplier
            )
            .exists()
        )
    order = (
        AwardContract.value_ron.desc().nulls_last()
        if sort == "value"
        else AwardContract.contract_date.desc().nulls_last()
    )
    total = session.scalar(
        select(func.count())
        .select_from(AwardContract)
        .join(AwardNotice, AwardContract.notice_id == AwardNotice.id)
        .where(*filters)
    )
    query = contracts().where(*filters).order_by(order, AwardContract.id.desc())
    if format == "csv":
        found: list[Contract] = []
        for start in range(0, total, CSV_BATCH):
            found += rows(session, query.limit(CSV_BATCH).offset(start))
        return contracts_csv(found)
    page = rows(session, query.limit(limit).offset(offset))
    return ContractPage(total=total, period=period(session), items=page)
