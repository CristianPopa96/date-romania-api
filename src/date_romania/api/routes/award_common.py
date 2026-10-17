"""What the award notice endpoints share: the filters on contracts, the source lines, and
the rows of a contract list."""

from typing import Annotated, Literal

from fastapi import Query
from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session, aliased

from date_romania import money
from date_romania.api.routes.common import last_fetched, record_source, ref
from date_romania.api.schemas import Contract, Period, Source, Winner
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardNoticeDetail,
    AwardWinner,
    Entity,
    SourceDocument,
)
from date_romania.sources import SEAP_AWARDS

Buyer = aliased(Entity)
Won = Literal["alone", "association"]


def notice_url(notice: AwardNotice) -> str:
    """The public page of a notice. Only notices of type 3 have a page we have checked."""
    if notice.notice_type_id == 3:
        return SEAP_AWARDS.record_url.format(id=notice.id)
    return SEAP_AWARDS.list_url


def awards_source(session: Session, *filters: ColumnElement[bool]) -> Source:
    """The source of a figure added up from many contracts signed in the period, and how
    many stored responses the contracts under `filters` were read from."""
    documents = session.scalar(
        select(func.count(AwardContract.source_document_id.distinct()))
        .join(AwardNotice, AwardContract.notice_id == AwardNotice.id)
        .where(*in_period(session), *filters)
    )
    return Source(
        publisher=SEAP_AWARDS.publisher,
        url=SEAP_AWARDS.list_url,
        fetched_at=last_fetched(session, SEAP_AWARDS),
        documents=documents,
    )


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


def contracts() -> Select:
    return (
        select(AwardContract, AwardNotice, Buyer, SourceDocument.fetched_at, SourceDocument.sha256)
        .join(AwardNotice, AwardContract.notice_id == AwardNotice.id)
        .outerjoin(Buyer, AwardNotice.buyer_cui == Buyer.cui)
        .join(SourceDocument, AwardContract.source_document_id == SourceDocument.id)
    )


def rows(session: Session, query: Select) -> list[Contract]:
    """Contracts with their winners, the winners read in one more query."""
    found_rows = session.execute(query).all()
    winners: dict[int, list[Winner]] = {}
    found = session.execute(
        select(AwardWinner, Entity)
        .outerjoin(Entity, AwardWinner.supplier_cui == Entity.cui)
        .where(AwardWinner.contract_id.in_([row[0].id for row in found_rows]))
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
            source=record_source(
                SEAP_AWARDS,
                contract,
                record=notice.notice_no,
                url=notice_url(notice),
                fetched_at=fetched_at,
                sha256=sha256,
            ),
        )
        for contract, notice, buyer, fetched_at, sha256 in found_rows
    ]
