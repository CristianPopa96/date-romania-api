"""The parts every list's `/overview` answer is built from (the site's list pattern,
DataTable): options of a choice filter, value bands, points over time, the parties after the
largest, and what each filter keeps out of an empty list. Each list says in its own answer
what its rows are (purchases, contracts, projects) and what its values count."""

from datetime import date

from pydantic import Field

from date_romania.api.schemas.common import Answer, EntityRef


class Option(Answer):
    """One option of a choice filter, with the rows it leaves under the other filters."""

    value: int
    count: int


class Band(Answer):
    """Rows whose value is from `start` up to `end` (excluded; null: no end)."""

    start: float
    end: float | None
    count: int


class Point(Answer):
    """The rows a list's totals count, in one month or one day, and their value."""

    start: date = Field(description="The first day of the month, or the day.")
    count: int
    value: float


class Others(Answer):
    """The rest of the value after the largest parties."""

    parties: int = Field(description="How many other parties, told apart by CUI or by text.")
    value: float


class Without(Answer):
    """How many rows one filter alone keeps out, for a list it leaves empty."""

    param: str
    count: int


class PartyOption(EntityRef):
    """An institution or company of a typeahead filter, with its rows under the other filters."""

    count: int


class CpvOption(Answer):
    """A CPV code of a typeahead filter, with its rows under the other filters."""

    code: str
    name: str | None
    count: int
