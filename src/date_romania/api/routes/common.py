"""What the endpoints share: parameters, the source line, and the queries behind several pages."""

import csv
import io
from collections.abc import Iterable
from datetime import date
from typing import Annotated, Literal

from fastapi import Depends, Query, Response
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.api.schemas import EntityRef, Partner, Source, Summary
from date_romania.dates import day_bounds
from date_romania.db import get_session
from date_romania.models import DirectPurchase, Entity, SourceDocument
from date_romania.sources import SEAP_DIRECT

Db = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Day = Annotated[date | None, Query(description="A day in Romanian time, YYYY-MM-DD.")]
Cpv = Annotated[
    str | None,
    Query(
        pattern=r"^\d{2,8}$",
        description="Start of a CPV code: 45 for the division of works, 4523 for a narrower class.",
    ),
]


Format = Annotated[Literal["json", "csv"], Query(description="csv gives the whole list as a file.")]


def cell(text: str | None) -> str | None:
    """A text cell as a spreadsheet may open it: one that starts like a formula gets a
    quote in front, so the program shows it instead of running it."""
    return f"'{text}" if text and text[0] in "=+-@" else text


def csv_file(header: list[str], rows: Iterable[list], filename: str) -> Response:
    """A whole list as a CSV file, with the mark at the start that makes spreadsheet
    programs read the diacritics."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content="﻿" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


def list_source(session: Session, *filters: ColumnElement[bool]) -> Source:
    """The source of a figure added up from many purchases: the SEAP list as last fetched,
    and how many stored responses the purchases under `filters` were read from."""
    fetched = session.scalar(
        select(func.max(SourceDocument.fetched_at)).where(SourceDocument.source == SEAP_DIRECT.key)
    )
    documents = session.scalar(
        select(func.count(DirectPurchase.source_document_id.distinct())).where(*filters)
    )
    return Source(
        publisher=SEAP_DIRECT.publisher,
        url=SEAP_DIRECT.list_url,
        fetched_at=fetched,
        documents=documents,
    )


def ref(entity: Entity | None) -> EntityRef | None:
    return entity and EntityRef.model_validate(entity)


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
        Partner(**ref(entity).model_dump(), accepted=accepted, value=value)
        for entity, accepted, value in rows
    ]
