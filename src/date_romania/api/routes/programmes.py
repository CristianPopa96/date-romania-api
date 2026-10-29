"""The Anghel Saligny programme: what the ministry paid, for which project, to which
builder, and the SEAP contracts a payment could be tied to."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from date_romania import pnias_links
from date_romania.api.routes.common import Db, Limit, Offset, last_fetched
from date_romania.api.routes.list_common import Order, ordered
from date_romania.api.routes.programme_list import PROJECT, ProjectFilters
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
)
from date_romania.sources import PNIAS_PAYMENTS, SEAP_EXPORTS, PublicSource

router = APIRouter(prefix="/programmes/anghel-saligny", tags=["programmes"])

_PAID = func.coalesce(func.sum(PniasPayment.amount), 0)


def source(session: Session, source: PublicSource, documents: int) -> Source:
    """The source of the programme's figures, and how many stored files the rows behind
    them were read from."""
    fetched = last_fetched(session, source)
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
        categories=session.scalars(
            select(PROJECT.c.category)
            .where(PROJECT.c.category.is_not(None))
            .group_by(PROJECT.c.category)
            .order_by(func.count().desc(), PROJECT.c.category)
        ).all(),
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
    filters: ProjectFilters,
    sort: Annotated[
        Literal["paid", "value"],
        Query(description="The amount paid, or the project's value as the ministry gives it."),
    ] = "paid",
    order: Order = "desc",
    limit: Limit = 20,
    offset: Offset = 0,
) -> ProjectPage:
    """The projects of the programme under the filters given, the most paid first, or in
    any column's order."""
    conditions = filters.all()
    column = PROJECT.c.total_value if sort == "value" else PROJECT.c.paid
    total = session.scalar(select(func.count()).select_from(PROJECT).where(*conditions))
    rows = session.execute(
        ordered(select(PROJECT).where(*conditions), column, order, PROJECT.c.project_id)
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
