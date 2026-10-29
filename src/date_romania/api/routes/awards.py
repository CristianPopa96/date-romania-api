"""Award notices and their contracts: one notice, and contracts by buyer or winner."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from date_romania import money
from date_romania.api.routes.award_common import (
    Buyer,
    contracts,
    in_period,
    notice_url,
    period,
    rows,
)
from date_romania.api.routes.award_csv import contracts_csv
from date_romania.api.routes.common import Db, Format, Limit, Offset, record_source, ref
from date_romania.api.routes.contract_filters import CONTRACTS, ContractFilters
from date_romania.api.routes.list_common import Order, ordered
from date_romania.api.schemas import AwardNoticeOut, ContractPage, NoticeDetail
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardNoticeDetail,
    AwardNoticeVersion,
    AwardWinner,
    Entity,
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
    filters: ContractFilters,
    sort: Annotated[
        Literal["date", "value", "supplier", "buyer", "newest"],
        Query(
            description="The day signed, the value in lei, the first winner's or the buyer's "
            "name; `newest` is the day, as before."
        ),
    ] = "date",
    order: Order = "desc",
    limit: Limit = 20,
    offset: Offset = 0,
    format: Format = "json",
) -> ContractPage:
    """Contracts signed in the period we hold, under the filters given, in any column's order.

    Framework agreements are left out: their value is a ceiling, and what is committed
    under them are their subsequent contracts, which are listed. The list is not complete:
    SEAP publishes many contracts weeks after they are signed.
    """
    conditions = [*in_period(session), *filters.all()]
    column = {
        "value": AwardContract.value_ron,
        "supplier": func.lower(_first_winner),
        "buyer": func.lower(func.coalesce(Buyer.name, AwardNotice.buyer_text)),
    }.get(sort, AwardContract.contract_date)
    total = session.scalar(select(func.count()).select_from(CONTRACTS).where(*conditions))
    query = ordered(contracts().where(*conditions), column, order, AwardContract.id)
    if format == "csv":
        # Read a batch at a time as the file is sent, never the whole list at once.
        return contracts_csv(
            contract
            for start in range(0, total, CSV_BATCH)
            for contract in rows(session, query.limit(CSV_BATCH).offset(start))
        )
    page = rows(session, query.limit(limit).offset(offset))
    return ContractPage(total=total, period=period(session), items=page)


# The name of a contract's first winner, as SEAP lists them, for sorting by it.
_first_winner = (
    select(func.coalesce(Entity.name, AwardWinner.supplier_text))
    .select_from(AwardWinner)
    .outerjoin(Entity, Entity.cui == AwardWinner.supplier_cui)
    .where(AwardWinner.contract_id == AwardContract.id)
    .order_by(AwardWinner.position)
    .limit(1)
    .correlate(AwardContract)
    .scalar_subquery()
)
