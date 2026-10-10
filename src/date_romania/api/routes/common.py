"""What the endpoints share: parameters, the source line, and the queries behind several pages."""

from datetime import date
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.api.schemas import EntityOut, EntityRef, Partner, Source, Summary
from date_romania.dates import day_bounds
from date_romania.db import get_session
from date_romania.models import DirectPurchase, Entity, SourceDocument
from date_romania.sources import SEAP_DIRECT

Db = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Day = Annotated[date | None, Query(description="A day in Romanian time, YYYY-MM-DD.")]


def in_period(date_from: date | None, date_to: date | None) -> list[ColumnElement[bool]]:
    """Filters for purchases finalized from `date_from` to `date_to`, both included."""
    filters = []
    if date_from:
        filters.append(DirectPurchase.finalized_at >= day_bounds(date_from)[0])
    if date_to:
        filters.append(DirectPurchase.finalized_at < day_bounds(date_to)[1])
    return filters


def summary(session: Session, *filters: ColumnElement[bool]) -> Summary:
    row = session.execute(select(*money.SUMMARY).where(*filters)).one()
    return Summary.model_validate(row._mapping)


def list_source(session: Session) -> Source:
    """The source of a figure added up from many purchases: the SEAP list as last fetched."""
    fetched = session.scalar(
        select(func.max(SourceDocument.fetched_at)).where(SourceDocument.source == SEAP_DIRECT.key)
    )
    return Source(publisher=SEAP_DIRECT.publisher, url=SEAP_DIRECT.list_url, fetched_at=fetched)


def ref(entity: Entity | None) -> EntityRef | None:
    return entity and EntityRef(cui=entity.cui, name=entity.name, kind=entity.kind)


def entity_out(entity: Entity) -> EntityOut:
    return EntityOut(
        cui=entity.cui,
        name=entity.name,
        kind=entity.kind,
        county=entity.county,
        locality=entity.locality,
    )


def top(
    session: Session,
    group_by: ColumnElement,
    filters: list[ColumnElement[bool]],
    limit: int,
) -> list[Partner]:
    """Entities on one side of the accepted purchases, by value, largest first."""
    rows = session.execute(
        select(Entity, func.count().label("accepted"), money.value.label("value"))
        .join(Entity, Entity.cui == group_by)
        .where(money.counted, *filters)
        .group_by(Entity.cui)
        .order_by(money.value.desc(), Entity.cui)
        .limit(limit)
    )
    return [
        Partner(cui=entity.cui, name=entity.name, kind=entity.kind, accepted=accepted, value=value)
        for entity, accepted, value in rows
    ]
