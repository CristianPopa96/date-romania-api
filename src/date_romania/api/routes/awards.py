"""Award notices and their contracts: one notice, contracts by buyer or winner, rankings."""

import csv
import io
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session, aliased

from date_romania import money
from date_romania.api.routes.common import Cpv, Db, Limit, ref
from date_romania.api.schemas import (
    AwardNoticeOut,
    Contract,
    ContractPage,
    NoticeDetail,
    Period,
    Source,
    Winner,
)
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

Buyer = aliased(Entity)
Won = Literal["alone", "association"]
Offset = Annotated[int, Query(ge=0)]
# A CSV file holds a whole list, not a page of it; it is read this many rows at a time.
CSV_BATCH = 1000


def _notice_url(notice: AwardNotice) -> str:
    """The public page of a notice. Only notices of type 3 have a page we have checked."""
    if notice.notice_type_id == 3:
        return SEAP_AWARDS.record_url.format(id=notice.id)
    return SEAP_AWARDS.list_url


def awards_source(session: Session) -> Source:
    fetched = session.scalar(
        select(func.max(SourceDocument.fetched_at)).where(SourceDocument.source == SEAP_AWARDS.key)
    )
    return Source(publisher=SEAP_AWARDS.publisher, url=SEAP_AWARDS.list_url, fetched_at=fetched)


def period(session: Session) -> Period:
    days = money.contracts_period(session)
    return Period(first_day=days and days[0], last_day=days and days[1])


def in_period(session: Session) -> list[ColumnElement[bool]]:
    """Filters for the contracts that totals may count: of a counted kind, signed in the
    period, in a notice still in force."""
    return [
        money.contract_counted,
        money.contract_in_force,
        *money.signed_in(money.contracts_period(session)),
    ]


def won_filters(won: Won | None) -> list[ColumnElement[bool]]:
    if won is None:
        return []
    return [money.is_association if won == "association" else ~money.is_association]


EuFunded = Annotated[
    bool | None,
    Query(
        description="true: notices with a lot paid from EU funds; false: notices that say no "
        "lot is. A notice whose form does not ask, or not read in detail, is only in the "
        "list without this filter."
    ),
]


def notice_filters(cpv: str | None, eu_funded: bool | None) -> list[ColumnElement[bool]]:
    """Filters on the notice a contract belongs to: its CPV code and its financing."""
    filters = []
    if cpv:
        filters.append(AwardNotice.cpv_code.startswith(cpv, autoescape=True))
    if eu_funded is not None:
        filters.append(
            select(AwardNoticeDetail.notice_id)
            .where(
                AwardNoticeDetail.notice_id == AwardNotice.id,
                AwardNoticeDetail.eu_funded.is_(eu_funded),
            )
            .exists()
        )
    return filters


def _contracts() -> Select:
    return (
        select(AwardContract, AwardNotice, Buyer, SourceDocument.fetched_at, SourceDocument.sha256)
        .join(AwardNotice, AwardContract.notice_id == AwardNotice.id)
        .outerjoin(Buyer, AwardNotice.buyer_cui == Buyer.cui)
        .join(SourceDocument, AwardContract.source_document_id == SourceDocument.id)
    )


def _rows(session: Session, query: Select) -> list[Contract]:
    """Contracts with their winners, the winners read in one more query."""
    rows = session.execute(query).all()
    winners: dict[int, list[Winner]] = {}
    found = session.execute(
        select(AwardWinner, Entity)
        .outerjoin(Entity, AwardWinner.supplier_cui == Entity.cui)
        .where(AwardWinner.contract_id.in_([row[0].id for row in rows]))
        .order_by(AwardWinner.contract_id, AwardWinner.position)
    )
    for winner, entity in found:
        winners.setdefault(winner.contract_id, []).append(
            Winner(supplier=ref(entity), text=winner.supplier_text, country=winner.country)
        )
    return [
        Contract(
            id=contract.id,
            notice_id=notice.id,
            notice_no=notice.notice_no,
            notice_title=notice.title,
            contract_no=contract.contract_no,
            title=contract.title,
            signed_at=contract.contract_date,
            kind=contract.kind,
            counted=money.is_counted_contract(contract.kind),
            lots=contract.lots,
            value=contract.value_ron,
            original_value=contract.value,
            currency=contract.currency,
            buyer=ref(buyer),
            buyer_text=notice.buyer_text,
            procedure_type=notice.procedure_type,
            cpv_code=notice.cpv_code,
            winners=winners.get(contract.id, []),
            source=Source(
                publisher=SEAP_AWARDS.publisher,
                record=notice.notice_no,
                url=_notice_url(notice),
                fetched_at=fetched_at,
                document_id=contract.source_document_id,
                sha256=sha256,
                parser_version=contract.parser_version,
            ),
        )
        for contract, notice, buyer, fetched_at, sha256 in rows
    ]


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
        detail=detail and NoticeDetail.model_validate(detail),
        contracts=sum(kinds.values()),
        ordinary=kinds.get(money.AWARD_CONTRACT, 0),
        frameworks=kinds.get(money.AWARD_FRAMEWORK, 0),
        subsequent=kinds.get(money.AWARD_SUBSEQUENT, 0),
        total=total,
        source=Source(
            publisher=SEAP_AWARDS.publisher,
            record=notice.notice_no,
            url=_notice_url(notice),
            fetched_at=fetched_at,
            document_id=notice.source_document_id,
            sha256=sha256,
            parser_version=notice.parser_version,
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
        _contracts()
        .where(own)
        .order_by(AwardContract.contract_date.nulls_last(), AwardContract.id)
        .limit(limit)
        .offset(offset)
    )
    return ContractPage(total=total, period=None, items=_rows(session, query))


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
    format: Annotated[
        Literal["json", "csv"], Query(description="csv gives the whole list as a file.")
    ] = "json",
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
    query = _contracts().where(*filters).order_by(order, AwardContract.id.desc())
    if format == "csv":
        rows: list[Contract] = []
        for start in range(0, total, CSV_BATCH):
            rows += _rows(session, query.limit(CSV_BATCH).offset(start))
        return _csv(rows)
    page = _rows(session, query.limit(limit).offset(offset))
    return ContractPage(total=total, period=period(session), items=page)


def _cell(text: str | None) -> str | None:
    """A text cell as a spreadsheet may open it: one that starts like a formula gets a
    quote in front, so the program shows it instead of running it."""
    return f"'{text}" if text and text[0] in "=+-@" else text


def _csv(contracts: list[Contract]) -> Response:
    """The list as a file; every row names its notice and where it was read."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "notice_no",
            "contract_no",
            "signed_at",
            "kind",
            "title",
            "buyer_cui",
            "buyer",
            "winner_cuis",
            "winners",
            "value_ron_without_vat",
            "source",
            "source_url",
            "fetched_at",
        ]
    )
    for contract in contracts:
        writer.writerow(
            [
                _cell(contract.notice_no),
                _cell(contract.contract_no),
                contract.signed_at and contract.signed_at.isoformat(),
                contract.kind,
                _cell(contract.title or contract.notice_title),
                contract.buyer and contract.buyer.cui,
                _cell(contract.buyer.name if contract.buyer else contract.buyer_text),
                "; ".join(str(w.supplier.cui) for w in contract.winners if w.supplier),
                _cell(
                    "; ".join(
                        (w.supplier.name if w.supplier else w.text) or "" for w in contract.winners
                    )
                ),
                contract.value,
                contract.source.publisher,
                contract.source.url,
                contract.source.fetched_at and contract.source.fetched_at.isoformat(),
            ]
        )
    return Response(
        # The mark at the start makes spreadsheet programs read the diacritics.
        content="﻿" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="contracte.csv"'},
    )
