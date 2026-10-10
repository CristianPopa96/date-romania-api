"""Shapes of the API answers. Amounts are in lei, without VAT, as SEAP publishes them."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from date_romania.money import (
    DIRECT_PURCHASE_LIMIT_GOODS_SERVICES_RON,
    DIRECT_PURCHASE_LIMIT_RON,
)

# The legal limits as the descriptions print them, e.g. "900,400 lei".
_LIMIT = f"{DIRECT_PURCHASE_LIMIT_RON:,.0f} lei"
_LIMIT_GOODS_SERVICES = f"{DIRECT_PURCHASE_LIMIT_GOODS_SERVICES_RON:,.0f} lei"


class Source(BaseModel):
    """Where a figure comes from, so the site can show it next to the figure."""

    publisher: str
    record: str | None = Field(None, description="The publisher's own number for the record.")
    url: str | None = None
    fetched_at: datetime | None = Field(None, description="When we last fetched it.")
    document_id: int | None = Field(None, description="Our id of the stored raw response.")


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


class Summary(BaseModel):
    """Direct purchases in a period. `value` counts accepted purchases only."""

    purchases: int = Field(description="All finished purchases, whatever their outcome.")
    accepted: int = Field(description="Purchases where the offer was accepted.")
    value: float = Field(description="Sum of the accepted purchases at or under `limit`.")
    above_limit: int = Field(
        description=f"Accepted purchases published with a value above {_LIMIT}, the highest "
        "legal limit for a direct purchase (the one for works). They are not counted in "
        "`value` and are listed separately. A goods or services purchase between its own "
        f"limit of {_LIMIT_GOODS_SERVICES} and this one is not marked."
    )
    above_limit_value: float
    first_day: date | None = Field(description="First day we have data for.")
    last_day: date | None


class Purchase(BaseModel):
    id: int
    code: str | None
    name: str | None
    state_id: int | None
    state: str | None
    cpv_code: str | None
    cpv_name: str | None
    buyer: EntityRef | None = Field(description="Null when SEAP gives no valid CUI.")
    buyer_text: str | None = Field(description="The buyer as SEAP writes it.")
    supplier: EntityRef | None
    supplier_text: str | None
    published_at: datetime | None
    finalized_at: datetime | None
    estimated_value: float | None
    value: float | None = Field(description="The closing value.")
    above_limit: bool = Field(
        description=f"The purchase was accepted with a value above {_LIMIT}, the highest "
        "legal limit for a direct purchase. Always false for a purchase that was not accepted."
    )
    source: Source


class PurchasePage(BaseModel):
    total: int
    items: list[Purchase]


class Partner(EntityRef):
    accepted: int
    value: float


class EntityPage(BaseModel):
    entity: EntityOut
    direct_purchases: Summary
    partners: list[Partner] = Field(
        description="The suppliers of an institution, or the institutions a supplier sold to, "
        "by value of accepted purchases."
    )
    source: Source


class RankingRow(Partner):
    rank: int


class Ranking(BaseModel):
    date_from: date | None
    date_to: date | None
    items: list[RankingRow]
    source: Source


class Stats(BaseModel):
    direct_purchases: Summary
    institutions: int = Field(description="Institutions with at least one purchase.")
    suppliers: int
    limit: float = Field(
        description="The limit used for `above_limit`: the legal one for works, the highest a "
        "direct purchase may have, in lei without VAT."
    )
    source: Source
