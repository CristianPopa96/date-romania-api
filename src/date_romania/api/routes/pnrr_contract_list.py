"""The filters of a list of PNRR financing contracts, and what the list says about itself
under them (`/programmes/pnrr/contracts/overview`).

One set of filters serves the list (`/programmes/pnrr/contracts`) and its figures. A
contract's value is its measures added up; its status and physical progress are those its
measures agree on (`per_contract`). A contract whose measures differ has neither, and is
counted apart. Natural persons' contracts are counted, never listed or named.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, String, and_, cast, func, join, or_, select

from date_romania.api.routes import list_common as lists
from date_romania.api.routes.common import Db, containing, ref
from date_romania.api.routes.list_common import NamedFilters
from date_romania.api.routes.pnrr_common import RAW_STATUS, find_measure, masked, per_contract
from date_romania.api.schemas import PnrrStatus
from date_romania.api.schemas.pnrr_contract_list import (
    BeneficiaryTypeOption,
    CountyOption,
    MeasureOption,
    PnrrBeneficiaryBar,
    PnrrContractOverview,
    PnrrContractSummary,
    PnrrStatusOption,
)
from date_romania.models import Entity, search_text
from date_romania.models import PnrrContract as Contract
from date_romania.models import PnrrContractLine as Line

router = APIRouter(prefix="/programmes/pnrr", tags=["programmes"])

# Each contract's measures added up, once for every query of the list.
SUMS = per_contract()
# A contract and its sums: the FROM of every count over the list.
CONTRACTS = join(Contract, SUMS, SUMS.c.contract_id == Contract.id)
# The edges of the value bands, in lei, and of the physical progress bands (0 to 1).
BAND_EDGES = (0, 100_000, 500_000, 1_000_000, 5_000_000, 25_000_000, 100_000_000)
PROGRESS_EDGES = (0, 0.25, 0.5, 0.75, 1)
# How many beneficiaries the chart names.
TOP_BENEFICIARIES = 5

_agreed = SUMS.c.statuses == 1
_progress = and_(SUMS.c.physicals == 1, SUMS.c.physical.is_not(None))


def has_status(wanted: list[PnrrStatus]) -> ColumnElement[bool]:
    """Contracts whose measures all give one of the statuses wanted."""
    return and_(
        _agreed, func.upper(func.trim(SUMS.c.status)).in_([RAW_STATUS[each] for each in wanted])
    )


def pnrr_contract_filters(
    session: Db,
    measure: Annotated[
        list[str] | None, Query(description="Measure codes, e.g. 'C10.I3'; any of them.")
    ] = None,
    county: Annotated[str | None, Query(description="As the dashboard writes it.")] = None,
    status_: Annotated[
        list[PnrrStatus] | None,
        Query(
            alias="status",
            description="Any of these statuses, as all of a contract's measures give it.",
        ),
    ] = None,
    beneficiary: Annotated[int | None, Query(description="The beneficiary's CUI.")] = None,
    beneficiary_type: Annotated[
        list[str] | None,
        Query(max_length=200, description="The kind of beneficiary as written; any of them."),
    ] = None,
    q: Annotated[
        str | None,
        Query(min_length=2, max_length=100, description="Words of the title or beneficiary."),
    ] = None,
    value_min: Annotated[float | None, Query(ge=0, description="Lei, included.")] = None,
    value_max: Annotated[float | None, Query(ge=0, description="Lei, excluded.")] = None,
    progress_min: Annotated[
        float | None, Query(ge=0, le=1, description="Physical progress, 0 to 1, included.")
    ] = None,
    progress_max: Annotated[
        float | None, Query(ge=0, le=1, description="Physical progress, 0 to 1, excluded.")
    ] = None,
) -> NamedFilters:
    named: dict[str, ColumnElement[bool]] = {}
    if measure:
        codes = [find_measure(session, code).code for code in measure]
        named["measure"] = Contract.id.in_(
            select(Line.contract_id).where(Line.measure_code.in_(codes))
        )
    if county:
        named["county"] = Contract.county == county
    if status_:
        named["status"] = has_status(status_)
    if beneficiary is not None:
        named["beneficiary"] = Contract.beneficiary_cui == beneficiary
    if beneficiary_type:
        named["beneficiary_type"] = Contract.beneficiary_type.in_(beneficiary_type)
    if q:
        named["q"] = and_(
            *(
                or_(
                    search_text(Contract.title).like(containing(word)),
                    search_text(Contract.beneficiary_name).like(containing(word)),
                )
                for word in q.split()
            )
        )
    if value_min is not None:
        named["value_min"] = SUMS.c.total >= value_min
    if value_max is not None:
        named["value_max"] = SUMS.c.total < value_max
    if progress_min is not None:
        named["progress_min"] = and_(_progress, SUMS.c.physical >= progress_min)
    if progress_max is not None:
        named["progress_max"] = and_(_progress, SUMS.c.physical < progress_max)
    return NamedFilters(named)


PnrrContractFilters = Annotated[NamedFilters, Depends(pnrr_contract_filters)]

# Natural persons' contracts are never in the list; they are counted in the summary.
LISTED = ~Contract.natural_person


@router.get("/contracts/overview")
def pnrr_contracts_overview(
    session: Db,
    filters: PnrrContractFilters,
    scope: Annotated[
        Literal["beneficiary", "measure"] | None,
        Query(
            description="The beneficiary or the measure whose list this is: `whole` counts "
            "all of its."
        ),
    ] = None,
) -> PnrrContractOverview:
    """The contracts under the filters given, in figures: how many and their value, the
    measures, counties and statuses with their counts, the contracts by value and progress,
    and the largest beneficiaries."""
    keep = [scope] if scope and scope in filters.named else []
    n, total, natural = session.execute(
        select(
            func.count().filter(LISTED),
            func.sum(SUMS.c.total).filter(LISTED),
            func.count().filter(Contract.natural_person),
        )
        .select_from(CONTRACTS)
        .where(*filters.all())
    ).one()
    measures = session.execute(
        select(Line.measure_code, func.count(Contract.id.distinct()))
        .select_from(CONTRACTS)
        .join(Line, Line.contract_id == Contract.id)
        .where(LISTED, *filters.all("measure"))
        .group_by(Line.measure_code)
        .order_by(func.count(Contract.id.distinct()).desc(), Line.measure_code)
    ).all()
    counties = session.execute(
        select(Contract.county, func.count())
        .select_from(CONTRACTS)
        .where(LISTED, Contract.county.is_not(None), *filters.all("county"))
        .group_by(Contract.county)
        .order_by(func.count().desc(), Contract.county)
    ).all()
    types = session.execute(
        select(Contract.beneficiary_type, func.count())
        .select_from(CONTRACTS)
        .where(LISTED, Contract.beneficiary_type.is_not(None), *filters.all("beneficiary_type"))
        .group_by(Contract.beneficiary_type)
        .order_by(func.count().desc(), Contract.beneficiary_type)
    ).all()
    # The largest beneficiaries are the options of the beneficiary filter: counted under
    # every other filter.
    by_beneficiary = [LISTED, *filters.all("beneficiary")]
    beneficiaries = _largest(session, by_beneficiary)
    by_status = [LISTED, *filters.all("status")]
    statuses = [
        PnrrStatusOption(
            value=each, count=lists.count(session, CONTRACTS, [*by_status, has_status([each])])
        )
        for each in RAW_STATUS
    ]
    return PnrrContractOverview(
        summary=PnrrContractSummary(contracts=n, value=total, natural_persons=natural),
        whole=lists.count(session, CONTRACTS, [LISTED, *(filters.named[k] for k in keep)]),
        measures=[MeasureOption(value=code, count=count) for code, count in measures],
        counties=[CountyOption(value=county, count=count) for county, count in counties],
        beneficiary_types=[
            BeneficiaryTypeOption(value=kind, count=count) for kind, count in types if kind.strip()
        ],
        statuses=statuses,
        measures_differ=lists.count(session, CONTRACTS, [*by_status, SUMS.c.statuses > 1]),
        bands=lists.bands(
            session,
            SUMS.c.total,
            BAND_EDGES,
            [LISTED, *filters.all("value_min", "value_max")],
            CONTRACTS,
        ),
        progress=lists.bands(
            session,
            SUMS.c.physical,
            PROGRESS_EDGES,
            [LISTED, _progress, *filters.all("progress_min", "progress_max")],
            CONTRACTS,
        ),
        beneficiaries=beneficiaries,
        others=lists.others(
            session,
            Contract.beneficiary_cui,
            Contract.beneficiary_name,
            func.sum(SUMS.c.total),
            by_beneficiary,
            [each.value for each in beneficiaries],
            CONTRACTS,
        ),
        without=lists.without(session, CONTRACTS, filters, keep, [LISTED]) if n == 0 else [],
    )


def _largest(session: Db, conditions: list[ColumnElement[bool]]) -> list[PnrrBeneficiaryBar]:
    """The beneficiaries with the largest value, told apart by CUI, or by name where the
    dashboard gives none."""
    key = func.coalesce(cast(Contract.beneficiary_cui, String), Contract.beneficiary_name)
    value = func.sum(SUMS.c.total)
    rows = session.execute(
        select(
            func.max(Contract.beneficiary_cui),
            func.min(Contract.beneficiary_name),
            func.count(),
            value,
        )
        .select_from(CONTRACTS)
        .where(key.is_not(None), *conditions)
        .group_by(key)
        .order_by(value.desc().nulls_last(), key)
        .limit(TOP_BENEFICIARIES)
    ).all()
    cuis = [cui for cui, *_ in rows if cui is not None]
    entities = {e.cui: e for e in session.scalars(select(Entity).where(Entity.cui.in_(cuis)))}
    return [
        PnrrBeneficiaryBar(
            name=masked(name), entity=ref(entities.get(cui)), contracts=n, value=total or 0
        )
        for cui, name, n, total in rows
    ]
