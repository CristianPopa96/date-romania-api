"""What every answer shares: the source line, entities and the period held."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class Source(BaseModel):
    """Where a figure comes from, so the site can show it next to the figure."""

    publisher: str
    record: str | None = Field(None, description="The publisher's own number for the record.")
    url: str | None = None
    fetched_at: datetime | None = Field(None, description="When we last fetched it.")
    document_id: int | None = Field(None, description="Our id of the stored raw response.")
    # Only for one record: a figure added up from many responses has no single file.
    sha256: str | None = Field(
        None, description="SHA-256 of the stored raw response, as it was received."
    )
    parser_version: int | None = Field(
        None, description="Version of the parser that read the record from it."
    )
    # Only for a figure added up from many records.
    documents: int | None = Field(
        None, description="How many stored responses the records behind the figure were read from."
    )


class EntityRef(BaseModel):
    # Filled straight from an `Entity` row.
    model_config = ConfigDict(from_attributes=True)

    cui: int
    name: str
    kind: str = Field(description="authority, company or other")


class EntityOut(EntityRef):
    county: str | None
    locality: str | None


class SearchResults(BaseModel):
    items: list[EntityOut]


class Period(BaseModel):
    """The days we hold. Contract totals count the contracts signed inside them."""

    first_day: date | None
    last_day: date | None
