"""What the endpoints share: parameters, the source line, and the queries behind several pages."""

import csv
import io
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from itertools import batched
from typing import Annotated, Literal

from fastapi import Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.api.schemas import EntityRef, Partner, Source, Summary
from date_romania.counties import CODES, county_name
from date_romania.dates import day_bounds
from date_romania.db import get_session
from date_romania.models import DirectPurchase, Entity, SourceDocument, search_text
from date_romania.sources import SEAP_DIRECT, PublicSource

Db = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
Day = Annotated[date | None, Query(description="A day in Romanian time, YYYY-MM-DD.")]
Cpv = Annotated[
    str | None,
    Query(
        pattern=r"^\d{2,8}$",
        description="Start of a CPV code: 45 for the division of works, 4523 for a narrower class.",
    ),
]

County = Annotated[
    str | None,
    Query(
        pattern=r"^[A-Z]{1,2}$",
        description="A county's two-letter code ('CJ'; București is 'B'), by where ANAF "
        "records the institution or company.",
    ),
]


def located_in(cui: ColumnElement, code: str) -> ColumnElement[bool]:
    """An institution or company that ANAF records in this county: one place only, so an
    association is never placed by one of its members."""
    name = county_name(CODES[code]) if code in CODES else None
    return cui.in_(select(Entity.cui).where(Entity.county == name))


Format = Annotated[Literal["json", "csv"], Query(description="csv gives the whole list as a file.")]


_LIKE_ESCAPES = str.maketrans({"\\": r"\\", "%": r"\%", "_": r"\_"})


def containing(text: str) -> ColumnElement[str]:
    """A LIKE pattern for text that contains `text` as typed (`%` and `_` are not
    wildcards), in the form search compares."""
    return search_text("%" + text.translate(_LIKE_ESCAPES) + "%")


# What a spreadsheet program may take for the start of a formula: the four signs, and a
# tab or a carriage return before one.
FORMULA_STARTS = "=+-@\t\r"
# Rows written to a file at a time, so a long list is never held whole in memory.
CSV_CHUNK = 1_000


def cell(text: str | None) -> str | None:
    """A text cell as a spreadsheet may open it: one that starts like a formula gets a
    quote in front, so the program shows it instead of running it."""
    return f"'{text}" if text and text[0] in FORMULA_STARTS else text


def csv_file(header: list[str], rows: Iterable[list], filename: str) -> StreamingResponse:
    """A whole list as a CSV file, with the mark at the start that makes spreadsheet
    programs read the diacritics. It is sent as it is written, a thousand rows at a time:
    `rows` should be read from the database as they come (`yield_per`)."""

    def chunks() -> Iterator[str]:
        out = io.StringIO()
        writer = csv.writer(out)
        out.write("\ufeff")
        writer.writerow(header)
        for batch in batched(rows, CSV_CHUNK):
            writer.writerows(batch)
            yield out.getvalue()
            out.seek(0)
            out.truncate()
        # The rest; with no rows at all, the header alone.
        if rest := out.getvalue():
            yield rest

    return StreamingResponse(
        chunks(),
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


def last_fetched(session: Session, source: PublicSource) -> datetime | None:
    """When anything of `source` was last fetched."""
    return session.scalar(
        select(func.max(SourceDocument.fetched_at)).where(SourceDocument.source == source.key)
    )


def record_source(
    source: PublicSource, row, *, record: str | None, url: str, fetched_at, sha256: str
) -> Source:
    """The source of one record: where it was read, and the stored answer and parser that
    read it. `row` is the stored record, with its `source_document_id` and `parser_version`."""
    return Source(
        publisher=source.publisher,
        record=record,
        url=url,
        fetched_at=fetched_at,
        document_id=row.source_document_id,
        sha256=sha256,
        parser_version=row.parser_version,
    )


def list_source(session: Session, *filters: ColumnElement[bool]) -> Source:
    """The source of a figure added up from many purchases: the SEAP list as last fetched,
    and how many stored responses the purchases under `filters` were read from."""
    documents = session.scalar(
        select(func.count(DirectPurchase.source_document_id.distinct())).where(*filters)
    )
    return Source(
        publisher=SEAP_DIRECT.publisher,
        url=SEAP_DIRECT.list_url,
        fetched_at=last_fetched(session, SEAP_DIRECT),
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
