"""The overview and the sources page."""

from datetime import date, datetime

from pydantic import Field

from date_romania.api.schemas.common import Answer, Source
from date_romania.api.schemas.purchases import (
    Summary,
)


class Stats(Answer):
    direct_purchases: Summary
    institutions: int = Field(description="Institutions with at least one purchase.")
    suppliers: int
    limit: float = Field(
        description="The limit used for `above_limit`: the legal one for works, the highest a "
        "direct purchase may have, in lei without VAT."
    )
    source: Source


class Dataset(Answer):
    """One source as we hold it, for the table that says what the site is built on."""

    key: str
    publisher: str
    first_day: date | None
    last_day: date | None
    records: int
    complete: bool = Field(
        description="False when the source publishes late, so the period keeps filling in."
    )
    fetched_at: datetime | None
    days_collected: int = Field(description="Days of the period read in full from the source.")
    days_partial: int = Field(
        description="Days of the period the source would not give in full; they wait to be read."
    )
    documents: int = Field(description="Raw answers kept from the source, each under its hash.")
    rejected_rows: int | None = Field(
        description="Rows of those answers the parser could not read, logged and left out. "
        "Null until every answer was seen by a parser that counts them."
    )
    counts: dict[str, int] = Field(
        description="What is held, by kind of row. `records` is the one the totals use."
    )


class Datasets(Answer):
    items: list[Dataset]
