"""The Anghel Saligny programme: what the ministry paid, for which project, to which
builder, and the SEAP contracts a payment could be tied to."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from date_romania import pnias_links
from date_romania.api.routes.common import Db, Limit
from date_romania.api.schemas import (
    Programme,
    ProgrammeFile,
    ProgrammeGroup,
    ProgrammeMatch,
    ProjectPage,
    ProjectRow,
    Source,
)
from date_romania.counties import county_name
from date_romania.models import (
    ExportContract,
    PniasPayment,
    SourceDocument,
    search_text,
)
from date_romania.sources import PNIAS_PAYMENTS, SEAP_EXPORTS, PublicSource

router = APIRouter(prefix="/programmes/anghel-saligny", tags=["programmes"])

State = Literal["one", "several", "none", "unnamed"]

_LIKE_ESCAPES = str.maketrans({"%": r"\%", "_": r"\_", "\\": r"\\"})

_PAID = func.coalesce(func.sum(PniasPayment.amount), 0)


def source(session: Session, source: PublicSource, documents: int) -> Source:
    """The source of the programme's figures, and how many stored files the rows behind
    them were read from."""
    fetched = session.scalar(
        select(func.max(SourceDocument.fetched_at)).where(SourceDocument.source == source.key)
    )
    return Source(
        publisher=source.publisher,
        record=source.dataset,
        # The exports have one dataset per year; the link goes to the latest.
        url=source.list_url.format(id=fetched.year if fetched else ""),
        fetched_at=fetched,
        documents=documents,
    )


def _files(session: Session, table) -> int:
    return session.scalar(select(func.count(table.source_document_id.distinct())))


def _groups(session: Session, column: ColumnElement, name=lambda key: key) -> list[ProgrammeGroup]:
    rows = session.execute(
        select(column, func.count(), _PAID, func.count(PniasPayment.project_id.distinct()))
        .group_by(column)
        .order_by(_PAID.desc(), column)
    )
    return [
        ProgrammeGroup(key=key, name=name(key), payments=payments, amount=amount, projects=projects)
        for key, payments, amount, projects in rows
    ]


def _match(rows) -> ProgrammeMatch:
    return ProgrammeMatch.model_validate(
        {state: {"count": count, "amount": amount} for state, count, amount in rows}
    )


@router.get("")
def programme(session: Db) -> Programme:
    """The programme as the payment files show it, and how many payments and projects
    could be tied to a SEAP contract. A payment is a settlement request the ministry paid."""
    payments, amount, projects, town_halls, builders, first_day, last_day = session.execute(
        select(
            func.count(),
            _PAID,
            func.count(PniasPayment.project_id.distinct()),
            func.count(func.distinct(PniasPayment.county, PniasPayment.town_hall)),
            func.count(PniasPayment.builder_cui.distinct()),
            func.min(PniasPayment.published_on),
            func.max(PniasPayment.published_on),
        )
    ).one()
    state = pnias_links.state().label("state")
    project = pnias_links.projects()
    files = session.execute(
        select(PniasPayment.published_on, func.count(), _PAID, func.count(PniasPayment.builder_cui))
        .group_by(PniasPayment.published_on)
        .order_by(PniasPayment.published_on)
    )
    contracts_first_day, contracts_last_day = session.execute(
        select(func.min(ExportContract.notice_date), func.max(ExportContract.notice_date))
    ).one()
    return Programme(
        payments=payments,
        amount=amount,
        projects=projects,
        town_halls=town_halls,
        builders=builders,
        first_day=first_day,
        last_day=last_day,
        networks=_groups(session, PniasPayment.network),
        counties=_groups(session, PniasPayment.county, county_name),
        files=[
            ProgrammeFile(published_on=day, payments=count, amount=total, with_tax_id=named)
            for day, count, total, named in files
        ],
        payments_match=_match(session.execute(select(state, func.count(), _PAID).group_by(state))),
        projects_match=_match(
            session.execute(
                select(project.c.match, func.count(), func.sum(project.c.paid)).group_by(
                    project.c.match
                )
            )
        ),
        payments_possible=_match(
            session.execute(
                select(state, func.count(), _PAID)
                .where(pnias_links.only_possible())
                .group_by(state)
            )
        ),
        contracts_first_day=contracts_first_day,
        contracts_last_day=contracts_last_day,
        source=source(session, PNIAS_PAYMENTS, _files(session, PniasPayment)),
        contracts_source=source(session, SEAP_EXPORTS, _files(session, ExportContract)),
    )


@router.get("/projects")
def projects(
    session: Db,
    county: Annotated[str | None, Query(description="As in `counties[].key`.")] = None,
    q: Annotated[
        str | None,
        Query(min_length=2, max_length=100, description="Part of the town hall or the investment."),
    ] = None,
    builder: Annotated[int | None, Query(description="The builder's CUI.")] = None,
    match: Annotated[State | None, Query(description="The match state of the project.")] = None,
    limit: Limit = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectPage:
    """The projects of the programme, the most paid first."""
    project = pnias_links.projects()
    filters = []
    if county:
        filters.append(project.c.county == county)
    if q:
        # The words are searched as typed: `%` and `_` are not wildcards.
        like = search_text("%" + q.translate(_LIKE_ESCAPES) + "%")
        filters.append(
            search_text(project.c.town_hall).like(like)
            | search_text(project.c.investment).like(like)
        )
    if builder:
        filters.append(
            project.c.project_id.in_(
                select(PniasPayment.project_id).where(PniasPayment.builder_cui == builder)
            )
        )
    if match:
        filters.append(project.c.match == match)
    total = session.scalar(select(func.count()).select_from(project).where(*filters))
    rows = session.execute(
        select(project)
        .where(*filters)
        .order_by(project.c.paid.desc(), project.c.project_id)
        .limit(limit)
        .offset(offset)
    )
    return ProjectPage(total=total, items=[project_row(row) for row in rows])


def project_row(row) -> ProjectRow:
    return ProjectRow(
        id=row.project_id,
        investment=row.investment,
        county=row.county,
        county_name=county_name(row.county),
        town_hall=row.town_hall,
        network=row.network,
        category=row.category,
        total_value=row.total_value,
        state_budget_value=row.state_budget_value,
        paid=row.paid,
        payments=row.payments,
        match=row.match,
    )
