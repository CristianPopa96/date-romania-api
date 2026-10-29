"""Every project of every programme held, as one list (design D22): `/projects`, its figures
(`/projects/overview`) and its file (`format=csv`).

The rows are the `project` table that `projects.build()` writes after the links change. A
natural person's project is never listed (Crispy, 22.10.2026): the summary counts them.
Text is served with valid personal codes masked, as on every page of a programme.
Figures of different programmes are never added: the value total comes only once one kind
of programme is chosen.
"""

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, and_, any_, func, literal, or_, select
from sqlalchemy.orm import Session

from date_romania import eu_programmes
from date_romania.api.routes import list_common as lists
from date_romania.api.routes.common import (
    Db,
    Format,
    Limit,
    Offset,
    cell,
    containing,
    csv_file,
    ref,
)
from date_romania.api.routes.eu_projects import lists_source
from date_romania.api.routes.list_common import NamedFilters, Order, ordered
from date_romania.api.routes.pnrr_common import edition_source, masked, newest_edition
from date_romania.api.routes.programmes import source as payments_source
from date_romania.api.schemas.common import Source
from date_romania.api.schemas.projects import (
    CountyRef,
    KindOption,
    ProgrammeOption,
    ProjectCountyOption,
    ProjectItem,
    ProjectKind,
    ProjectList,
    ProjectsOverview,
    ProjectsSummary,
    ProjectStatus,
    ProjectStatusOption,
    Reach,
    ReachOption,
)
from date_romania.counties import CODES, county_name
from date_romania.models import Entity, PniasPayment, PnrrEdition, Project, search_text
from date_romania.personal_id import mask_cnp
from date_romania.projects import KINDS, REACHES
from date_romania.sources import PNIAS_PAYMENTS

router = APIRouter(prefix="/projects", tags=["projects"])

# The edges of the value bands, in lei.
BAND_EDGES = (0, 100_000, 500_000, 1_000_000, 5_000_000, 25_000_000, 100_000_000)
STATUSES: tuple[ProjectStatus, ...] = ("in_progress", "finished", "terminated")
# Natural persons are never listed by name.
LISTED = ~Project.natural_person
# A financing contract number, as typed: digits with letters, slashes or dots ('1850DOT').
_NUMBER = re.compile(r"\d")


def programme_name(programme: str) -> tuple[str, str | None]:
    """A programme's name and period, from its code in the `project` table."""
    if programme == "AS":
        return "Anghel Saligny", None
    if programme == "PNRR":
        return "PNRR", None
    held = eu_programmes.BY_CODE.get(programme)
    return (held.name, held.period) if held else (programme, None)


def project_filters(
    kind: Annotated[
        list[ProjectKind] | None, Query(description="Any of these kinds of programme.")
    ] = None,
    programme: Annotated[
        list[str] | None,
        Query(description="Any of these programmes: 'AS', 'PNRR', or a cohesion code 'POR'."),
    ] = None,
    county: Annotated[str | None, Query(description="A county's code, as in `counties`.")] = None,
    beneficiary: Annotated[int | None, Query(description="The beneficiary's CUI.")] = None,
    status: Annotated[list[ProjectStatus] | None, Query(description="Any of these.")] = None,
    reach: Annotated[
        list[Reach] | None, Query(description="Any of these last steps followed.")
    ] = None,
    q: Annotated[
        str | None,
        Query(
            min_length=2,
            max_length=100,
            description="Words of the title or the beneficiary's name, a SMIS code or a "
            "financing contract number.",
        ),
    ] = None,
    value_min: Annotated[float | None, Query(ge=0, description="Lei, included.")] = None,
    value_max: Annotated[float | None, Query(ge=0, description="Lei, excluded.")] = None,
) -> NamedFilters:
    named: dict[str, ColumnElement[bool]] = {}
    if kind:
        named["kind"] = Project.kind.in_(kind)
    if programme:
        named["programme"] = Project.programme.in_(programme)
    if county:
        named["county"] = literal(county).op("=")(any_(Project.counties))
    if beneficiary is not None:
        named["beneficiary"] = Project.beneficiary_cui == beneficiary
    if status:
        named["status"] = Project.status.in_(status)
    if reach:
        named["reach"] = Project.reach.in_(reach)
    if q:
        named["q"] = _search(q)
    if value_min is not None:
        named["value_min"] = Project.value >= value_min
    if value_max is not None:
        named["value_max"] = Project.value < value_max
    return NamedFilters(named)


ProjectFilters = Annotated[NamedFilters, Depends(project_filters)]


def _search(q: str) -> ColumnElement[bool]:
    """Every word in the title or the beneficiary's name; or the programme's key (a SMIS
    code) or its financing contract number, as typed."""
    words = and_(
        *(
            or_(
                search_text(Project.title).like(containing(word)),
                search_text(Project.beneficiary_name).like(containing(word)),
            )
            for word in q.split()
        )
    )
    typed = q.strip()
    # A personal code never finds what it is written in: it is never shown either.
    if not _NUMBER.search(q) or mask_cnp(typed, checked=True) != typed:
        return words
    by_number = func.upper(Project.number) == typed.upper()
    if typed.isdigit():
        return or_(words, by_number, Project.key == int(typed))
    return or_(words, by_number)


def _one_kind(session: Session, filters: NamedFilters) -> bool:
    """Whether a programme is chosen and the projects filtered are all of one kind, so their
    values may be added."""
    if "kind" not in filters.named and "programme" not in filters.named:
        return False
    kinds = session.scalar(
        select(func.count(Project.kind.distinct())).where(LISTED, *filters.all())
    )
    return kinds <= 1


@router.get("")
def project_list(
    session: Db,
    filters: ProjectFilters,
    sort: Annotated[Literal["value"], Query(description="The project's value.")] = "value",
    order: Order = "desc",
    limit: Limit = 25,
    offset: Offset = 0,
    format: Format = "json",
) -> ProjectList:
    """Every project of every programme under the filters, the largest first. Sorting
    across programmes orders them; it never adds their values."""
    conditions = [LISTED, *filters.all()]
    query = ordered(select(Project).where(*conditions), Project.value, order, Project.id)
    entities = _entities(session)
    if format == "csv":
        return _csv(session.scalars(query.execution_options(yield_per=1_000)), entities)
    total = lists.count(session, Project, conditions)
    rows = session.scalars(query.limit(limit).offset(offset)).all()
    return ProjectList(total=total, items=[_item(row, entities(row)) for row in rows])


def _entities(session: Session):
    """The beneficiary of a row as its entity, read once per CUI."""
    held: dict[int, Entity | None] = {}

    def entity(row: Project) -> Entity | None:
        if row.beneficiary_cui is None:
            return None
        if row.beneficiary_cui not in held:
            held[row.beneficiary_cui] = session.get(Entity, row.beneficiary_cui)
        return held[row.beneficiary_cui]

    return entity


def _item(row: Project, entity: Entity | None) -> ProjectItem:
    name, period = programme_name(row.programme)
    return ProjectItem(
        kind=row.kind,
        key=row.key,
        programme=row.programme,
        programme_name=name,
        period=period,
        title=masked(row.title),
        number=masked(row.number),
        beneficiary_name=masked(row.beneficiary_name),
        beneficiary=ref(entity),
        counties=[CountyRef(code=code, name=county_name(CODES[code])) for code in row.counties],
        value=row.value,
        status=row.status,
        status_written=row.status_written,
        reach=row.reach,
        gap=row.gap,
    )


def _csv(rows, entities):
    header = [
        "programme",
        "key",
        "title",
        "financing_contract",
        "beneficiary_cui",
        "beneficiary",
        "counties",
        "value_ron",
        "status",
        "followed_to",
        "step_not_followed",
    ]
    lines = (
        [
            programme_name(row.programme)[0],
            row.key,
            cell(masked(row.title)),
            cell(masked(row.number)),
            row.beneficiary_cui,
            cell(entities(row).name if entities(row) else masked(row.beneficiary_name)),
            " ".join(row.counties),
            row.value,
            row.status_written,
            row.reach,
            row.gap,
        ]
        for row in rows
    )
    return csv_file(header, lines, "proiecte.csv")


@router.get("/overview")
def projects_overview(
    session: Db,
    filters: ProjectFilters,
    beneficiary: Annotated[int | None, Query(description="The beneficiary's CUI.")] = None,
) -> ProjectsOverview:
    """The projects under the filters in figures: how many, how many are followed to the
    companies, the natural persons' left out, and each choice's options with their counts."""
    conditions = [LISTED, *filters.all()]
    n, companies = session.execute(
        select(func.count(), func.count().filter(Project.reach == "companies")).where(*conditions)
    ).one()
    natural = lists.count(session, Project, [Project.natural_person, *filters.all()])
    value = None
    if _one_kind(session, filters):
        value = session.scalar(select(func.coalesce(func.sum(Project.value), 0)).where(*conditions))
    counties = func.unnest(Project.counties).label("value")
    county_rows = session.execute(
        select(counties, func.count())
        .where(LISTED, *filters.all("county"))
        .group_by(counties)
        .order_by(func.count().desc(), counties)
    )
    return ProjectsOverview(
        summary=ProjectsSummary(
            projects=n, companies=companies, natural_persons=natural, value=value
        ),
        whole=lists.count(session, Project, [LISTED]),
        beneficiary=ref(session.get(Entity, beneficiary)) if beneficiary else None,
        kinds=[
            KindOption(value=value, count=count)
            for value, count in _counts(session, Project.kind, filters, "kind")
            if value in KINDS
        ],
        programmes=[
            ProgrammeOption(
                value=code,
                kind=kind,
                name=programme_name(code)[0],
                period=programme_name(code)[1],
                count=count,
            )
            for (code, kind), count in _programmes(session, filters)
        ],
        counties=[
            ProjectCountyOption(value=code, name=county_name(CODES[code]), count=count)
            for code, count in county_rows
            if code in CODES
        ],
        statuses=[
            ProjectStatusOption(value=value, count=count)
            for value, count in _counts(session, Project.status, filters, "status")
            if value in STATUSES
        ],
        reaches=[
            ReachOption(value=value, count=count)
            for value, count in _counts(session, Project.reach, filters, "reach")
            if value in REACHES
        ],
        bands=lists.bands(
            session, Project.value, BAND_EDGES, [LISTED, *filters.all("value_min", "value_max")]
        ),
        without=lists.without(session, Project, filters, base=[LISTED]) if n == 0 else [],
        sources=_sources(session),
    )


def _counts(session: Session, column, filters: NamedFilters, own: str):
    return session.execute(
        select(column, func.count())
        .where(LISTED, *filters.all(own))
        .group_by(column)
        .order_by(func.count().desc(), column)
    ).all()


def _programmes(session: Session, filters: NamedFilters):
    rows = session.execute(
        select(Project.programme, Project.kind, func.count())
        .where(LISTED, *filters.all("programme"))
        .group_by(Project.programme, Project.kind)
        .order_by(func.count().desc(), Project.programme)
    )
    return [((code, kind), count) for code, kind, count in rows]


def _sources(session: Session) -> list[Source]:
    """The sources of the three programmes, each with the files its rows were read from."""
    sources = [
        payments_source(
            session,
            PNIAS_PAYMENTS,
            session.scalar(select(func.count(PniasPayment.source_document_id.distinct()))),
        )
    ]
    if session.scalar(select(func.count()).select_from(PnrrEdition)):
        sources.append(edition_source(session, newest_edition(session)))
    sources.append(lists_source(session))
    return sources
