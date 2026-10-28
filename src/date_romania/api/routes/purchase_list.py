"""The filters of the list of direct purchases, and what the list says about itself under
them: its figures and charts (`/overview`) and the options of its typeahead filters.

One set of filters serves the list, its file, its figures and its options, so the page shows
the same purchases everywhere. Each filter is kept under the name of its parameter, so an
option can be counted under every filter but its own, and an empty list can say which filter
emptied it.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, Date, String, and_, case, cast, func, literal, or_, select

from date_romania import money
from date_romania.api.routes.common import Cpv, Day, Db, containing, in_period, ref, summary, top
from date_romania.api.schemas.purchase_list import (
    Band,
    CpvOption,
    Option,
    Others,
    PartyOption,
    Point,
    PurchaseOverview,
    Without,
)
from date_romania.dates import BUCHAREST
from date_romania.models import DirectPurchase, Entity, search_text

router = APIRouter(tags=["direct purchases"])

Side = Literal["buyer", "supplier"]

# The edges of the value bands, in lei without VAT; the legal limits are edges of their own.
BAND_EDGES = (
    0,
    1_000,
    5_000,
    10_000,
    50_000,
    100_000,
    int(money.DIRECT_PURCHASE_LIMIT_GOODS_SERVICES_RON),
    int(money.DIRECT_PURCHASE_LIMIT_RON),
)
# Purchases spread over fewer days than this are drawn per day.
DAYS_FOR_MONTHS = 62
TOP_PARTIES = 5
OPTIONS = 8

_CUI = {"buyer": DirectPurchase.buyer_cui, "supplier": DirectPurchase.supplier_cui}
_TEXT = {"buyer": DirectPurchase.buyer_text, "supplier": DirectPurchase.supplier_text}


@dataclass
class PurchaseFilters:
    """The filters given, each under the name of its parameter, in the order of the parameters."""

    named: dict[str, ColumnElement[bool]]

    def all(self, *but: str) -> list[ColumnElement[bool]]:
        return [condition for name, condition in self.named.items() if name not in but]


def purchase_filters(
    buyer: Annotated[int | None, Query(description="CUI of the buying institution.")] = None,
    supplier: Annotated[int | None, Query(description="CUI of the supplier.")] = None,
    q: Annotated[
        str | None,
        Query(max_length=100, description="Words of the name, the DA code or either party."),
    ] = None,
    state: Annotated[
        list[int] | None, Query(description="SEAP state ids, any of them; 7 is accepted.")
    ] = None,
    contract_type: Annotated[
        list[int] | None,
        Query(description="1 goods, 2 services, 3 works, 0 for a type not known; any of them."),
    ] = None,
    value_min: Annotated[
        float | None, Query(ge=0, description="Lei without VAT, included.")
    ] = None,
    value_max: Annotated[
        float | None, Query(ge=0, description="Lei without VAT, excluded.")
    ] = None,
    cpv: Cpv = None,
    date_from: Day = None,
    date_to: Day = None,
) -> PurchaseFilters:
    named: dict[str, ColumnElement[bool]] = {}
    if buyer is not None:
        named["buyer"] = DirectPurchase.buyer_cui == buyer
    if supplier is not None:
        named["supplier"] = DirectPurchase.supplier_cui == supplier
    if words := (q or "").split():
        texts = (
            DirectPurchase.name,
            DirectPurchase.code,
            DirectPurchase.supplier_text,
            DirectPurchase.buyer_text,
        )
        # Every word, each anywhere: in the name, the code or the text of a party.
        named["q"] = and_(
            *(or_(*(search_text(text).like(containing(word)) for text in texts)) for word in words)
        )
    if state:
        named["state"] = DirectPurchase.state_id.in_(state)
    if contract_type:
        known = DirectPurchase.contract_type_id.in_([kind for kind in contract_type if kind])
        named["contract_type"] = (
            or_(known, DirectPurchase.contract_type_id.is_(None)) if 0 in contract_type else known
        )
    if value_min is not None:
        named["value_min"] = DirectPurchase.closing_value >= value_min
    if value_max is not None:
        named["value_max"] = DirectPurchase.closing_value < value_max
    if cpv:
        named["cpv"] = DirectPurchase.cpv_code.startswith(cpv, autoescape=True)
    if date_from:
        named["date_from"] = in_period(date_from, None)[0]
    if date_to:
        named["date_to"] = in_period(None, date_to)[0]
    return PurchaseFilters(named)


Filters = Annotated[PurchaseFilters, Depends(purchase_filters)]


def _count(session: Db, conditions: list[ColumnElement[bool]]) -> int:
    return session.scalar(select(func.count()).select_from(DirectPurchase).where(*conditions))


def _options(session: Db, column, conditions: list[ColumnElement[bool]]) -> list[Option]:
    rows = session.execute(
        select(column.label("value"), func.count().label("purchases"))
        .where(*conditions)
        .group_by(column)
        .order_by(func.count().desc(), column)
    )
    return [Option(value=value, purchases=purchases) for value, purchases in rows]


def _bands(session: Db, conditions: list[ColumnElement[bool]]) -> list[Band]:
    band = case(
        *(
            (DirectPurchase.closing_value < end, start)
            for start, end in zip(BAND_EDGES, BAND_EDGES[1:], strict=False)
        ),
        else_=BAND_EDGES[-1],
    )
    counted = dict(
        session.execute(
            select(band, func.count())
            .where(DirectPurchase.closing_value.is_not(None), *conditions)
            .group_by(band)
        ).all()
    )
    ends = [*BAND_EDGES[1:], None]
    return [
        Band(start=start, end=end, purchases=counted.get(start, 0))
        for start, end in zip(BAND_EDGES, ends, strict=True)
    ]


def _points(session: Db, conditions, step: str) -> list[Point]:
    start = cast(func.date_trunc(step, money.day), Date) if step == "month" else money.day
    rows = session.execute(
        select(start.label("start"), func.count().label("accepted"), money.value.label("value"))
        .where(money.counted, *conditions)
        .group_by(start)
        .order_by(start)
    )
    return [Point.model_validate(row._mapping) for row in rows]


def _others(session: Db, side: Side, conditions, parties) -> Others:
    key = func.coalesce(cast(_CUI[side], String), _TEXT[side])
    count, value = session.execute(
        select(func.count(key.distinct()), money.value).where(money.counted, *conditions)
    ).one()
    return Others(
        parties=max(count - len(parties), 0),
        value=round(float(value) - sum(party.value for party in parties), 2),
    )


@router.get("/direct-purchases/overview")
def direct_purchases_overview(
    session: Db,
    filters: Filters,
    scope: Annotated[
        Side | None,
        Query(
            description="The party whose list this is: the figures say what part of it "
            "the filters keep, and the chart of parties names the other side."
        ),
    ] = None,
) -> PurchaseOverview:
    """The list of direct purchases under the filters given, in figures: the summary, accepted
    value per month (or per day), the largest parties, the options of each choice filter and
    the purchases by value band."""
    conditions = filters.all()
    found = summary(session, *conditions)
    whole = _count(session, filters.all(*[name for name in filters.named if name != scope]))
    newest = session.scalar(select(func.max(DirectPurchase.finalized_at)))
    span = found.first_day and found.last_day and (found.last_day - found.first_day).days
    step = "day" if span is not None and span < DAYS_FOR_MONTHS else "month"
    party: Side = "buyer" if scope == "supplier" else "supplier"
    parties = top(session, _CUI[party], conditions, TOP_PARTIES)
    without = []
    if found.purchases == 0:
        without = [
            Without(param=name, purchases=_count(session, filters.all(name)))
            for name in filters.named
            if name != scope
        ]
    return PurchaseOverview(
        summary=found,
        whole=whole,
        last_day_held=newest and newest.astimezone(BUCHAREST).date(),
        step=step,
        points=_points(session, conditions, step) if found.accepted else [],
        party=party,
        parties=parties,
        others=_others(session, party, conditions, parties),
        states=_options(session, DirectPurchase.state_id, filters.all("state")),
        contract_types=_options(
            session,
            func.coalesce(DirectPurchase.contract_type_id, literal(0)),
            filters.all("contract_type"),
        ),
        bands=_bands(session, filters.all("value_min", "value_max")),
        without=without,
    )


@router.get("/direct-purchases/parties")
def direct_purchase_parties(
    session: Db,
    filters: Filters,
    side: Annotated[Side, Query(description="The side to list.")],
    find: Annotated[
        str | None, Query(max_length=100, description="Words of the name, or the CUI.")
    ] = None,
) -> list[PartyOption]:
    """The parties on one side of the purchases the other filters give, most purchases first:
    the options of a typeahead filter."""
    cui = _CUI[side]
    conditions = filters.all(side)
    if find and find.strip().isdecimal():
        conditions.append(cui == int(find.strip()))
    elif find:
        conditions += [search_text(Entity.name).like(containing(word)) for word in find.split()]
    rows = session.execute(
        select(Entity, func.count().label("purchases"))
        .select_from(DirectPurchase)
        .join(Entity, Entity.cui == cui)
        .where(*conditions)
        .group_by(Entity.cui)
        .order_by(func.count().desc(), Entity.cui)
        .limit(OPTIONS)
    )
    return [
        PartyOption(**ref(entity).model_dump(), purchases=purchases) for entity, purchases in rows
    ]


@router.get("/direct-purchases/cpv-codes")
def direct_purchase_cpv_codes(
    session: Db,
    filters: Filters,
    find: Annotated[
        str | None, Query(max_length=100, description="The start of a code, or words of its name.")
    ] = None,
) -> list[CpvOption]:
    """The CPV codes of the purchases the other filters give, most purchases first: the
    options of the CPV filter."""
    conditions = filters.all("cpv")
    if find and find.strip().isdecimal():
        conditions.append(DirectPurchase.cpv_code.startswith(find.strip(), autoescape=True))
    elif find:
        conditions += [
            search_text(DirectPurchase.cpv_name).like(containing(word)) for word in find.split()
        ]
    rows = session.execute(
        select(
            DirectPurchase.cpv_code,
            func.max(DirectPurchase.cpv_name),
            func.count().label("purchases"),
        )
        .where(DirectPurchase.cpv_code.is_not(None), *conditions)
        .group_by(DirectPurchase.cpv_code)
        .order_by(func.count().desc(), DirectPurchase.cpv_code)
        .limit(OPTIONS)
    )
    return [CpvOption(code=code, name=name, purchases=n) for code, name, n in rows]
