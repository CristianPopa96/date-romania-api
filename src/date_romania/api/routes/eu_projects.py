"""EU cohesion projects: the programmes held, the projects, one project with its payments
where its programme publishes them.

Text is served with valid personal codes masked. A programme's figures describe the day of
its own list: they are never added to another programme's.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania.api.routes.common import Db, Limit, Offset, last_fetched, ref
from date_romania.api.routes.eu_project_list import EuProjectFilters, status
from date_romania.api.routes.list_common import Order, ordered
from date_romania.api.schemas import (
    EuBeneficiary,
    EuFunds,
    EuPayment,
    EuProgramme,
    EuProject,
    EuProjectPage,
    EuProjectRow,
    Source,
)
from date_romania.eu_programmes import BY_CODE, PROGRAMMES
from date_romania.models import Entity, SourceDocument, held_by_map
from date_romania.models import EuProject as Project
from date_romania.models import EuProjectPayment as Payment
from date_romania.personal_id import mask_cnp
from date_romania.sources import EU_MAP, EU_PROJECTS

router = APIRouter(prefix="/programmes/eu-funds", tags=["programmes"])


def _text(value: str | None) -> str | None:
    return mask_cnp(value, checked=True)


@router.get("")
def eu_funds(session: Db) -> EuFunds:
    """The programmes held, each from its newest list: projects, value and paid so far."""
    rows = {
        row.programme: row
        for row in session.execute(
            select(
                Project.programme,
                func.count().label("projects"),
                func.sum(Project.total_value).label("total"),
                func.sum(Project.paid).label("paid"),
                func.max(Project.cut_off).label("cut_off"),
            ).group_by(Project.programme)
        )
    }
    return EuFunds(
        programmes=[
            EuProgramme(
                code=each.code,
                name=each.name,
                period=each.period,
                projects=row.projects,
                total=row.total,
                paid=row.paid,
                cut_off=row.cut_off,
            )
            for each in PROGRAMMES
            if (row := rows.get(each.code))
        ],
        source=lists_source(session),
    )


def lists_source(session: Session, *filters) -> Source:
    """The MIPE lists behind the projects `filters` pick, and the map where it holds some of
    them: how many files were read for them."""
    mapped = session.scalar(
        select(func.count()).select_from(Project).where(*filters, held_by_map())
    )
    return Source(
        publisher=EU_PROJECTS.publisher,
        record=f"{EU_PROJECTS.dataset} · {EU_MAP.dataset}" if mapped else EU_PROJECTS.dataset,
        url=EU_PROJECTS.list_url,
        fetched_at=max(
            (day for day in (last_fetched(session, each) for each in (EU_PROJECTS, EU_MAP)) if day),
            default=None,
        ),
        documents=session.scalar(
            select(func.count(Project.source_document_id.distinct())).where(*filters)
        ),
    )


@router.get("/projects")
def projects(
    session: Db,
    filters: EuProjectFilters,
    sort: Annotated[
        Literal["value", "paid"], Query(description="The total value, or the amount paid.")
    ] = "value",
    order: Order = "desc",
    limit: Limit = 20,
    offset: Offset = 0,
) -> EuProjectPage:
    """Projects under the filters given, the largest first, or in any column's order."""
    conditions = filters.all()
    column = Project.paid if sort == "paid" else Project.total_value
    total = session.scalar(select(func.count()).select_from(Project).where(*conditions))
    query = select(Project, Entity).outerjoin(Entity, Entity.cui == Project.entity_cui)
    rows = session.execute(
        ordered(query.where(*conditions), column, order, Project.smis).limit(limit).offset(offset)
    )
    return EuProjectPage(
        total=total or 0,
        items=[EuProjectRow(**_row(project, entity)) for project, entity in rows],
    )


def _row(project: Project, entity: Entity | None) -> dict:
    return {
        "smis": project.smis,
        "programme": project.programme,
        "title": _text(project.title),
        "beneficiary": EuBeneficiary(
            name=_text(project.beneficiary_name),
            entity=ref(entity),
            confidence=project.entity_confidence if entity else None,
            method=project.entity_method if entity else None,
        ),
        "county": project.county,
        "total": project.total_value,
        "paid": project.paid,
        "status": status(project.status),
        "status_written": _text(project.status),
    }


@router.get("/projects/{smis}")
def project(session: Db, smis: int) -> EuProject:
    """One project, from its programme's newest list, with its payments one by one where
    the programme publishes them (Health)."""
    found = session.get(Project, smis)
    if found is None:
        raise HTTPException(404, f"No EU project with SMIS {smis}")
    entity = session.get(Entity, found.entity_cui) if found.entity_cui else None
    doc = session.get(SourceDocument, found.source_document_id)
    payments, payments_source = _payments(session, found)
    return EuProject(
        **_row(found, entity),
        programme_name=BY_CODE[found.programme].name,
        period=found.period,
        partners=_text(found.partners),
        summary=_text(found.summary),
        beneficiary_type=found.beneficiary_type,
        locality=found.locality,
        starts_on=found.starts_on,
        ends_on=found.ends_on,
        cofinancing_rate=found.cofinancing_rate,
        eu=found.eu_value,
        cut_off=found.cut_off,
        payments=payments,
        payments_source=payments_source,
        source=Source(
            publisher=EU_PROJECTS.publisher,
            record=EU_MAP.dataset
            if doc.source == EU_MAP.key
            else f"Lista proiectelor contractate {found.programme}",
            url=doc.url,
            fetched_at=doc.fetched_at,
            document_id=doc.id,
            sha256=doc.sha256,
            parser_version=found.parser_version,
        ),
    )


def _payments(session: Session, project: Project) -> tuple[list[EuPayment] | None, Source | None]:
    """A project's payments, where its programme publishes them one by one."""
    if not BY_CODE[project.programme].health_page:
        return None, None
    rows = session.scalars(
        select(Payment)
        .where(Payment.smis == project.smis)
        .order_by(Payment.paid_on.desc().nulls_last(), Payment.position)
    ).all()
    return [
        EuPayment(paid_on=row.paid_on, amount=row.amount, kind=row.kind, funding=row.funding)
        for row in rows
    ], Source(
        publisher=EU_PROJECTS.publisher,
        record="Plăți efectuate",
        url=EU_PROJECTS.list_url,
        fetched_at=session.scalar(
            select(func.max(SourceDocument.fetched_at)).where(
                SourceDocument.id.in_(select(Payment.source_document_id))
            )
        ),
        documents=session.scalar(select(func.count(Payment.source_document_id.distinct()))),
    )
