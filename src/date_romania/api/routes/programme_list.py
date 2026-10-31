"""The filters of the list of Anghel Saligny projects, and what the list says about itself
under them (`/programmes/anghel-saligny/projects/overview`).

One set of filters serves the list (`/programmes/anghel-saligny/projects`) and its figures.
A project is one row of `pnias_links.projects()`: its latest payment's description of it,
what was paid in all, and whether a SEAP contract was found for it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, func, select

from date_romania import pnias_links
from date_romania.api.routes import list_common as lists
from date_romania.api.routes.common import Db, containing, ref
from date_romania.api.routes.list_common import NamedFilters
from date_romania.api.schemas import Match
from date_romania.api.schemas.programme_list import (
    MatchOption,
    ProgrammeCountyOption,
    ProjectOverview,
    ProjectSummary,
    WorksOption,
)
from date_romania.counties import county_name
from date_romania.models import Entity, PniasPayment, search_text

router = APIRouter(prefix="/programmes/anghel-saligny", tags=["programmes"])

# One row per project, for every query of the list.
PROJECT = pnias_links.projects()
# The edges of the bands of the amount paid, in lei.
BAND_EDGES = (0, 100_000, 500_000, 1_000_000, 5_000_000, 25_000_000)


def project_filters(
    county: Annotated[str | None, Query(description="As in `counties[].value`.")] = None,
    q: Annotated[
        str | None,
        Query(min_length=2, max_length=100, description="Part of the town hall or the investment."),
    ] = None,
    builder: Annotated[int | None, Query(description="The builder's CUI.")] = None,
    match: Annotated[
        list[Match] | None, Query(description="Any of these match states of the project.")
    ] = None,
    category: Annotated[
        list[str] | None, Query(description="Kinds of works as the ministry writes them.")
    ] = None,
    paid_min: Annotated[float | None, Query(ge=0, description="Lei paid, included.")] = None,
    paid_max: Annotated[float | None, Query(ge=0, description="Lei paid, excluded.")] = None,
) -> NamedFilters:
    named: dict[str, ColumnElement[bool]] = {}
    if county:
        named["county"] = PROJECT.c.county == county
    if q:
        # The words are searched as typed: `%` and `_` are not wildcards.
        like = containing(q)
        named["q"] = search_text(PROJECT.c.town_hall).like(like) | search_text(
            PROJECT.c.investment
        ).like(like)
    if builder:
        named["builder"] = PROJECT.c.project_id.in_(
            select(PniasPayment.project_id).where(PniasPayment.builder_found_cui == builder)
        )
    if match:
        named["match"] = PROJECT.c.match.in_(match)
    if category:
        named["category"] = PROJECT.c.category.in_(category)
    if paid_min is not None:
        named["paid_min"] = PROJECT.c.paid >= paid_min
    if paid_max is not None:
        named["paid_max"] = PROJECT.c.paid < paid_max
    return NamedFilters(named)


ProjectFilters = Annotated[NamedFilters, Depends(project_filters)]


@router.get("/projects/overview")
def projects_overview(
    session: Db,
    filters: ProjectFilters,
    builder: Annotated[int | None, Query(description="The builder's CUI.")] = None,
) -> ProjectOverview:
    """The projects under the filters given, in figures: how many, their payments and what
    was paid, the options of each choice filter with their counts, and the projects by the
    amount paid."""
    n, payments, paid = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(PROJECT.c.payments), 0),
            func.coalesce(func.sum(PROJECT.c.paid), 0),
        )
        .select_from(PROJECT)
        .where(*filters.all())
    ).one()
    paid_by_county = func.coalesce(func.sum(PROJECT.c.paid), 0)
    counties = session.execute(
        select(PROJECT.c.county, func.count(), paid_by_county)
        .where(*filters.all("county"))
        .group_by(PROJECT.c.county)
        .order_by(paid_by_county.desc(), PROJECT.c.county)
    )
    return ProjectOverview(
        summary=ProjectSummary(projects=n, payments=payments, paid=paid),
        whole=lists.count(session, PROJECT, []),
        builder=ref(session.get(Entity, builder)) if builder else None,
        counties=[
            ProgrammeCountyOption(value=key, name=county_name(key), count=count, paid=amount)
            for key, count, amount in counties
        ],
        matches=[
            MatchOption(value=option.value, count=option.count)
            for option in _options(session, PROJECT.c.match, filters.all("match"))
        ],
        categories=[
            WorksOption(value=option.value, count=option.count)
            for option in _options(
                session,
                PROJECT.c.category,
                [PROJECT.c.category.is_not(None), *filters.all("category")],
            )
        ],
        bands=lists.bands(
            session, PROJECT.c.paid, BAND_EDGES, filters.all("paid_min", "paid_max"), PROJECT
        ),
        without=lists.without(session, PROJECT, filters) if n == 0 else [],
    )


def _options(session: Db, column, conditions: list[ColumnElement[bool]]):
    """A text column's values with their counts: `lists.options` takes numbers."""
    return session.execute(
        select(column.label("value"), func.count().label("count"))
        .select_from(PROJECT)
        .where(*conditions)
        .group_by(column)
        .order_by(func.count().desc(), column)
    ).all()
