"""What a list of award contracts says about itself under its filters
(`contract_filters.py`): its figures and charts (`/award-contracts/overview`) and the options
of its typeahead filters.

Contracts won alone and by associations are never added together for a company: the site
asks for a company's contracts one way at a time (`won`). A buyer's contracts are each
counted once, whoever won them; its winners are ranked by what they won alone.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, func, select

from date_romania import money
from date_romania.api.routes import list_common as lists
from date_romania.api.routes.award_common import in_period, period
from date_romania.api.routes.common import Db, containing, ref
from date_romania.api.routes.contract_filters import CONTRACTS, ContractFilters, eu_funded_filter
from date_romania.api.routes.list_common import OPTIONS
from date_romania.api.schemas import ContractTotals
from date_romania.api.schemas.contract_list import (
    ContractOverview,
    ContractParty,
    ContractSummary,
    WonOption,
)
from date_romania.api.schemas.lists import CpvOption, Option, PartyOption
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardWinner,
    Entity,
    search_text,
)

router = APIRouter(tags=["award notices"])

Side = Literal["buyer", "supplier"]

# The edges of the value bands, in lei without VAT.
BAND_EDGES = (0, 10_000, 100_000, 500_000, 1_000_000, 5_000_000, 25_000_000, 100_000_000)
TOP_PARTIES = 5

# reading it here instead of joining the winners never counts its contract twice.
_sole_cui = (
    select(func.min(AwardWinner.supplier_cui))
    .where(AwardWinner.contract_id == AwardContract.id)
    .correlate(AwardContract)
    .scalar_subquery()
)
_sole_text = (
    select(func.min(AwardWinner.supplier_text))
    .where(AwardWinner.contract_id == AwardContract.id)
    .correlate(AwardContract)
    .scalar_subquery()
)
_CUI = {"buyer": AwardNotice.buyer_cui, "supplier": _sole_cui}
_TEXT = {"buyer": AwardNotice.buyer_text, "supplier": _sole_text}


def _summary(session: Db, conditions: list[ColumnElement[bool]]) -> ContractSummary:
    row = session.execute(
        select(
            func.count().label("contracts"),
            money.contract_value.label("value"),
            func.count().filter(AwardContract.value_ron.is_(None)).label("without_value"),
            func.min(money.contract_day).label("first_day"),
            func.max(money.contract_day).label("last_day"),
        )
        .select_from(CONTRACTS)
        .where(*conditions)
    ).one()
    return ContractSummary.model_validate(row._mapping)


def _parties(session: Db, side: Side, conditions) -> list[ContractParty]:
    rows = session.execute(
        select(Entity, func.count().label("contracts"), money.contract_value.label("value"))
        .select_from(CONTRACTS)
        .join(Entity, Entity.cui == _CUI[side])
        .where(*conditions)
        .group_by(Entity.cui)
        .order_by(money.contract_value.desc(), Entity.cui)
        .limit(TOP_PARTIES)
    )
    return [
        ContractParty(**ref(entity).model_dump(), contracts=n, value=value)
        for entity, n, value in rows
    ]


def _count(session: Db, conditions) -> int:
    return lists.count(session, CONTRACTS, conditions)


@router.get("/award-contracts/overview")
def award_contracts_overview(
    session: Db,
    filters: ContractFilters,
    scope: Annotated[
        Side | None,
        Query(
            description="The party whose list this is: the figures say what part of it the "
            "filters keep, and the chart of parties names the other side."
        ),
    ] = None,
) -> ContractOverview:
    """The contracts of the list under the filters given, in figures: the summary, the value
    per month (or per day), the largest parties, the options of each choice filter and the
    contracts by value band."""
    base = in_period(session)
    conditions = [*base, *filters.all()]
    # A company's contracts are a list of one kind: won alone, or in associations.
    keep = [name for name in ("buyer", "supplier", "won") if name in filters.named]
    keep = keep if scope == "supplier" else [name for name in keep if name != "won"]
    found = _summary(session, conditions)
    whole = _count(session, [*base, *(filters.named[name] for name in keep)])
    step = lists.step(found.first_day, found.last_day)
    party: Side = "buyer" if scope == "supplier" else "supplier"
    ranked = conditions if party == "buyer" else [*conditions, ~money.is_association]
    parties = _parties(session, party, ranked)
    associations = None
    if party == "supplier":
        n, value = session.execute(
            select(func.count(), money.contract_value)
            .select_from(CONTRACTS)
            .where(*conditions, money.is_association)
        ).one()
        associations = ContractTotals(contracts=n, value=value)
    won_counts = session.execute(
        select(
            func.count().filter(~money.is_association), func.count().filter(money.is_association)
        )
        .select_from(CONTRACTS)
        .where(*base, *filters.all("won"))
    ).one()
    eu = session.execute(
        select(
            func.count().filter(eu_funded_filter(True)),
            func.count().filter(eu_funded_filter(False)),
        )
        .select_from(CONTRACTS)
        .where(*base, *filters.all("eu_funded"))
    ).one()
    return ContractOverview(
        summary=found,
        whole=whole,
        period=period(session),
        step=step,
        points=lists.points(
            session, money.contract_day, money.contract_value, conditions, step, CONTRACTS
        )
        if found.contracts
        else [],
        party=party,
        parties=parties,
        others=lists.others(
            session,
            _CUI[party],
            _TEXT[party],
            money.contract_value,
            ranked,
            [each.value for each in parties],
            CONTRACTS,
        ),
        associations=associations,
        won=[
            WonOption(value="alone", count=won_counts[0]),
            WonOption(value="association", count=won_counts[1]),
        ],
        kinds=lists.options(session, AwardContract.kind, [*base, *filters.all("kind")], CONTRACTS),
        eu_funded=[Option(value=1, count=eu[0]), Option(value=0, count=eu[1])],
        bands=lists.bands(
            session,
            AwardContract.value_ron,
            BAND_EDGES,
            [*base, *filters.all("value_min", "value_max")],
            CONTRACTS,
        ),
        without=lists.without(session, CONTRACTS, filters, keep, base)
        if found.contracts == 0
        else [],
    )


@router.get("/award-contracts/parties")
def award_contract_parties(
    session: Db,
    filters: ContractFilters,
    side: Annotated[Side, Query(description="The side to list.")],
    find: Annotated[
        str | None, Query(max_length=100, description="Words of the name, or the CUI.")
    ] = None,
) -> list[PartyOption]:
    """The parties on one side of the contracts the other filters give, most contracts
    first: the options of a typeahead filter. A member of an association is one of them."""
    conditions = [*in_period(session), *filters.all(side)]
    if side == "buyer":
        query = select(Entity, func.count().label("count")).select_from(CONTRACTS)
        query = query.join(Entity, Entity.cui == AwardNotice.buyer_cui)
    else:
        query = select(Entity, func.count(AwardContract.id.distinct()).label("count"))
        query = query.select_from(CONTRACTS).join(
            AwardWinner, AwardWinner.contract_id == AwardContract.id
        )
        query = query.join(Entity, Entity.cui == AwardWinner.supplier_cui)
    if find and find.strip().isdecimal():
        conditions.append(Entity.cui == int(find.strip()))
    elif find:
        conditions += [search_text(Entity.name).like(containing(word)) for word in find.split()]
    rows = session.execute(
        query.where(*conditions)
        .group_by(Entity.cui)
        .order_by(func.count().desc(), Entity.cui)
        .limit(OPTIONS)
    )
    return [PartyOption(**ref(entity).model_dump(), count=n) for entity, n in rows]


@router.get("/award-contracts/cpv-codes")
def award_contract_cpv_codes(
    session: Db,
    filters: ContractFilters,
    find: Annotated[
        str | None, Query(max_length=100, description="The start of a code, or words of its name.")
    ] = None,
) -> list[CpvOption]:
    """The CPV codes of the notices of the contracts the other filters give, most contracts
    first: the options of the CPV filter."""
    conditions = [*in_period(session), *filters.all("cpv")]
    if find and find.strip().isdecimal():
        conditions.append(AwardNotice.cpv_code.startswith(find.strip(), autoescape=True))
    elif find:
        conditions += [
            search_text(AwardNotice.cpv_name).like(containing(word)) for word in find.split()
        ]
    rows = session.execute(
        select(AwardNotice.cpv_code, func.max(AwardNotice.cpv_name), func.count())
        .select_from(CONTRACTS)
        .where(AwardNotice.cpv_code.is_not(None), *conditions)
        .group_by(AwardNotice.cpv_code)
        .order_by(func.count().desc(), AwardNotice.cpv_code)
        .limit(OPTIONS)
    )
    return [CpvOption(code=code, name=name, count=n) for code, name, n in rows]
