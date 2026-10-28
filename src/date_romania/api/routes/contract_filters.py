"""The filters of a list of award contracts, each kept under the name of its parameter: one
set serves the list (`/award-contracts`), its file, its figures and the options of its
typeahead filters (`contract_list.py`), so the page shows the same contracts everywhere.

Every count over the list adds `award_common.in_period`: contracts signed in the period
held, of a counted kind (never a framework agreement), in a notice still in force.
"""

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import ColumnElement, and_, join, or_, select

from date_romania import money
from date_romania.api.routes.award_common import Won
from date_romania.api.routes.common import Cpv, Day, containing
from date_romania.api.routes.list_common import NamedFilters
from date_romania.dates import day_bounds
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardNoticeDetail,
    AwardWinner,
    search_text,
)

# A contract and its notice: the FROM of every count over the list.
CONTRACTS = join(AwardContract, AwardNotice, AwardContract.notice_id == AwardNotice.id)


def winner(cui: ColumnElement | int) -> ColumnElement[bool]:
    return (
        select(AwardWinner.contract_id)
        .where(AwardWinner.contract_id == AwardContract.id, AwardWinner.supplier_cui == cui)
        .exists()
    )


# The winner of a contract won alone. SEAP can list one company twice: it is still one, and


def eu_funded_filter(funded: bool) -> ColumnElement[bool]:
    return (
        select(AwardNoticeDetail.notice_id)
        .where(
            AwardNoticeDetail.notice_id == AwardNotice.id, AwardNoticeDetail.eu_funded.is_(funded)
        )
        .exists()
    )


def contract_filters(
    buyer: Annotated[int | None, Query(description="CUI of the buying institution.")] = None,
    supplier: Annotated[int | None, Query(description="CUI of a winner.")] = None,
    q: Annotated[
        str | None,
        Query(
            max_length=100,
            description="Words of the contract's or notice's title, its numbers, or a party.",
        ),
    ] = None,
    won: Annotated[
        Won | None, Query(description="By one company, or by an association of several.")
    ] = None,
    kind: Annotated[
        list[int] | None, Query(description="1 ordinary, 3 subsequent; any of them.")
    ] = None,
    eu_funded: Annotated[
        bool | None,
        Query(
            description="true: notices with a lot paid from EU funds; false: notices that say "
            "no lot is. A notice whose form does not say is only in the list without it."
        ),
    ] = None,
    value_min: Annotated[float | None, Query(ge=0, description="Lei, included.")] = None,
    value_max: Annotated[float | None, Query(ge=0, description="Lei, excluded.")] = None,
    cpv: Cpv = None,
    date_from: Day = None,
    date_to: Day = None,
) -> NamedFilters:
    named: dict[str, ColumnElement[bool]] = {}
    if buyer is not None:
        named["buyer"] = AwardNotice.buyer_cui == buyer
    if supplier is not None:
        named["supplier"] = winner(supplier)
    if words := (q or "").split():
        texts = (
            AwardContract.title,
            AwardContract.contract_no,
            AwardNotice.title,
            AwardNotice.notice_no,
            AwardNotice.buyer_text,
        )

        def anywhere(word: str) -> ColumnElement[bool]:
            like = containing(word)
            winner = (
                select(AwardWinner.contract_id)
                .where(
                    AwardWinner.contract_id == AwardContract.id,
                    search_text(AwardWinner.supplier_text).like(like),
                )
                .exists()
            )
            return or_(*(search_text(text).like(like) for text in texts), winner)

        named["q"] = and_(*(anywhere(word) for word in words))
    if won:
        named["won"] = money.is_association if won == "association" else ~money.is_association
    if kind:
        named["kind"] = AwardContract.kind.in_(kind)
    if eu_funded is not None:
        named["eu_funded"] = eu_funded_filter(eu_funded)
    if value_min is not None:
        named["value_min"] = AwardContract.value_ron >= value_min
    if value_max is not None:
        named["value_max"] = AwardContract.value_ron < value_max
    if cpv:
        named["cpv"] = AwardNotice.cpv_code.startswith(cpv, autoescape=True)
    if date_from:
        named["date_from"] = AwardContract.contract_date >= day_bounds(date_from)[0]
    if date_to:
        named["date_to"] = AwardContract.contract_date < day_bounds(date_to)[1]
    return NamedFilters(named)


ContractFilters = Annotated[NamedFilters, Depends(contract_filters)]
