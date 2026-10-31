"""The filters of a list of EU cohesion projects, and what the list says about itself under
them (`/programmes/eu-funds/projects/overview`).

One set of filters serves the list (`/programmes/eu-funds/projects`) and its figures. A
programme's figures describe the day of its own list, so they are never added to another
programme's: the overview gives the value and the amount paid per programme, each with
its day, and no sum across them.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, and_, func, or_, select

from date_romania.api.routes import list_common as lists
from date_romania.api.routes.common import Db, containing
from date_romania.api.routes.list_common import NamedFilters
from date_romania.api.schemas import EuStatus
from date_romania.api.schemas.eu_project_list import (
    EuProjectOverview,
    EuProjectSummary,
    ProgrammeOption,
    StatusOption,
)
from date_romania.eu_programmes import BY_CODE, status
from date_romania.models import EuProject as Project
from date_romania.models import programme_day, search_text

router = APIRouter(prefix="/programmes/eu-funds", tags=["programmes"])

# The edges of the value bands, in lei.
BAND_EDGES = (0, 100_000, 500_000, 1_000_000, 5_000_000, 25_000_000, 100_000_000, 500_000_000)


def _spelled(session: Db, wanted: list[EuStatus]) -> ColumnElement[bool]:
    """The projects whose status, however the lists write it, is one of ours wanted."""
    spellings = session.scalars(select(Project.status).distinct()).all()
    return Project.status.in_([each for each in spellings if status(each) in wanted])


def eu_project_filters(
    session: Db,
    programme: Annotated[
        list[str] | None, Query(description="Programme codes, e.g. 'POR'; any of them.")
    ] = None,
    beneficiary: Annotated[int | None, Query(description="The beneficiary's CUI.")] = None,
    status_: Annotated[
        list[EuStatus] | None, Query(alias="status", description="Any of these statuses.")
    ] = None,
    q: Annotated[
        str | None,
        Query(
            min_length=2,
            max_length=100,
            description="Words of the title or the beneficiary's name, or a SMIS code.",
        ),
    ] = None,
    value_min: Annotated[float | None, Query(ge=0, description="Lei, included.")] = None,
    value_max: Annotated[float | None, Query(ge=0, description="Lei, excluded.")] = None,
) -> NamedFilters:
    named: dict[str, ColumnElement[bool]] = {}
    if programme:
        named["programme"] = Project.programme.in_(programme)
    if beneficiary is not None:
        named["beneficiary"] = Project.entity_cui == beneficiary
    if status_:
        named["status"] = _spelled(session, status_)
    if q:
        words = and_(
            *(
                or_(
                    search_text(Project.title).like(containing(word)),
                    search_text(Project.beneficiary_name).like(containing(word)),
                )
                for word in q.split()
            )
        )
        # A SMIS code typed alone finds its project too.
        code = q.strip()
        named["q"] = (
            or_(words, Project.smis == int(code)) if code.isdecimal() and len(code) <= 9 else words
        )
    if value_min is not None:
        named["value_min"] = Project.total_value >= value_min
    if value_max is not None:
        named["value_max"] = Project.total_value < value_max
    return NamedFilters(named)


EuProjectFilters = Annotated[NamedFilters, Depends(eu_project_filters)]


@router.get("/projects/overview")
def eu_projects_overview(
    session: Db,
    filters: EuProjectFilters,
    scope: Annotated[
        Literal["beneficiary"] | None,
        Query(description="The beneficiary whose list this is: `whole` counts all of its."),
    ] = None,
) -> EuProjectOverview:
    """The projects under the filters given, in figures: how many, the value and the amount
    paid per programme (never added across programmes), the options of each choice filter,
    and the projects by value band."""
    conditions = filters.all()
    keep = ["beneficiary"] if scope and "beneficiary" in filters.named else []
    count, first, last = session.execute(
        select(func.count(), func.min(Project.starts_on), func.max(Project.starts_on)).where(
            *conditions
        )
    ).one()
    programmes = [
        ProgrammeOption(**row._mapping, paid_as=BY_CODE[row.value].paid_as)
        for row in session.execute(
            select(
                Project.programme.label("value"),
                func.count().label("count"),
                func.sum(Project.total_value).label("total"),
                func.sum(Project.paid).label("paid"),
                programme_day().label("cut_off"),
            )
            .where(*filters.all("programme"))
            .group_by(Project.programme)
            .order_by(func.count().desc(), Project.programme)
        )
    ]
    by_status: dict[EuStatus | None, int] = {}
    for written, n in session.execute(
        select(Project.status, func.count()).where(*filters.all("status")).group_by(Project.status)
    ):
        ours = status(written)
        by_status[ours] = by_status.get(ours, 0) + n
    return EuProjectOverview(
        summary=EuProjectSummary(projects=count, first_start=first, last_start=last),
        whole=lists.count(session, Project, [filters.named[name] for name in keep]),
        programmes=programmes,
        statuses=[
            StatusOption(value=each, count=by_status.get(each, 0))
            for each in ("in_progress", "finished", "terminated")
        ],
        other_statuses=by_status.get(None, 0),
        bands=lists.bands(
            session, Project.total_value, BAND_EDGES, filters.all("value_min", "value_max")
        ),
        without=lists.without(session, Project, filters, keep) if count == 0 else [],
    )
