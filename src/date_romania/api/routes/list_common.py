"""What every list of the site's list pattern (DataTable) shares: its filters kept by name,
its order, and the figures of `/overview` (options, value bands, points over time, the
largest parties, the filter that empties it).

A list module declares its own filters and which columns they read; these pieces count and
group whatever it gives them. Money stays with the list: each passes the condition of the
rows its totals count and the sum that is their value.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import ColumnElement, Date, Select, String, case, cast, func, select
from sqlalchemy.orm import Session

from date_romania.api.schemas.lists import Band, Option, Others, Point, Without

Order = Literal["desc", "asc"]

# Rows spread over fewer days than this are drawn per day, else per month.
DAYS_FOR_MONTHS = 62
# How many options a typeahead filter offers.
OPTIONS = 8


@dataclass
class NamedFilters:
    """The filters given, each under the name of its parameter, in the order of the
    parameters: an option is counted under every filter but its own, and an empty list can
    say which filter emptied it."""

    named: dict[str, ColumnElement[bool]]

    def all(self, *but: str) -> list[ColumnElement[bool]]:
        return [condition for name, condition in self.named.items() if name not in but]


def ordered(query: Select, column: ColumnElement, order: Order, tie: ColumnElement) -> Select:
    """The list in one column's order, empty values last, ties broken by `tie` the same way,
    so a page never repeats or skips a row."""
    first = column.asc() if order == "asc" else column.desc()
    second = tie.asc() if order == "asc" else tie.desc()
    return query.order_by(first.nulls_last(), second)


def count(session: Session, table, conditions: list[ColumnElement[bool]]) -> int:
    return session.scalar(select(func.count()).select_from(table).where(*conditions))


def options(session: Session, column, conditions: list[ColumnElement[bool]]) -> list[Option]:
    """The values of a choice filter, most rows first, each with the rows it would give."""
    rows = session.execute(
        select(column.label("value"), func.count().label("count"))
        .where(*conditions)
        .group_by(column)
        .order_by(func.count().desc(), column)
    )
    return [Option(value=value, count=n) for value, n in rows]


def bands(
    session: Session,
    value: ColumnElement,
    edges: Sequence[float],
    conditions: list[ColumnElement[bool]],
) -> list[Band]:
    """Rows by value, from each edge up to the next (excluded); the last band has no end."""
    band = case(
        *((value < end, start) for start, end in zip(edges, edges[1:], strict=False)),
        else_=edges[-1],
    )
    counted = dict(
        session.execute(
            select(band, func.count()).where(value.is_not(None), *conditions).group_by(band)
        ).all()
    )
    ends = [*edges[1:], None]
    return [
        Band(start=start, end=end, count=counted.get(start, 0))
        for start, end in zip(edges, ends, strict=True)
    ]


def step(first_day: date | None, last_day: date | None) -> Literal["month", "day"]:
    """Days for rows that span under two months, else months."""
    if first_day and last_day and (last_day - first_day).days < DAYS_FOR_MONTHS:
        return "day"
    return "month"


def points(
    session: Session,
    day: ColumnElement,
    value: ColumnElement,
    conditions: list[ColumnElement[bool]],
    by: Literal["month", "day"],
) -> list[Point]:
    """The rows given and their value per month or per day; `value` is a sum."""
    start = cast(func.date_trunc(by, day), Date) if by == "month" else day
    rows = session.execute(
        select(start.label("start"), func.count().label("count"), value.label("value"))
        .where(*conditions)
        .group_by(start)
        .order_by(start)
    )
    return [Point.model_validate(row._mapping) for row in rows]


def others(
    session: Session,
    cui: ColumnElement,
    text: ColumnElement,
    value: ColumnElement,
    conditions: list[ColumnElement[bool]],
    largest: Sequence[float],
) -> Others:
    """The parties after the largest: how many (told apart by CUI, or by name where there is
    none) and their value. `largest` are the values of the parties shown."""
    key = func.coalesce(cast(cui, String), text)
    n, total = session.execute(select(func.count(key.distinct()), value).where(*conditions)).one()
    return Others(
        parties=max(n - len(largest), 0),
        value=round(float(total or 0) - sum(largest), 2),
    )


def without(
    session: Session, table, filters: NamedFilters, keep: Sequence[str] = ()
) -> list[Without]:
    """For a list its filters leave empty: what each one alone keeps out, in the order of the
    parameters. Filters in `keep` (whose list it is) are never offered."""
    return [
        Without(param=name, count=count(session, table, filters.all(name)))
        for name in filters.named
        if name not in keep
    ]
