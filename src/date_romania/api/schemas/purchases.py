"""Direct purchases: one purchase, the lists and totals, the rankings."""

from datetime import date, datetime

from pydantic import Field

from date_romania.api.schemas.common import Answer, EntityOut, EntityRef, Source
from date_romania.money import (
    DIRECT_PURCHASE_LIMIT_GOODS_SERVICES_RON,
    DIRECT_PURCHASE_LIMIT_RON,
)

# The legal limits as the descriptions print them, e.g. "900,400 lei".
_LIMIT = f"{DIRECT_PURCHASE_LIMIT_RON:,.0f} lei"
_LIMIT_GOODS_SERVICES = f"{DIRECT_PURCHASE_LIMIT_GOODS_SERVICES_RON:,.0f} lei"


class Summary(Answer):
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


class Purchase(Answer):
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


class PurchasePage(Answer):
    total: int
    items: list[Purchase]


class Partner(EntityRef):
    accepted: int
    value: float


class EntityPage(Answer):
    entity: EntityOut
    direct_purchases: Summary
    partners: list[Partner] = Field(
        description="The suppliers of an institution, or the institutions a supplier sold to, "
        "by value of accepted purchases."
    )
    source: Source


class RankingRow(Partner):
    rank: int


class Ranking(Answer):
    date_from: date | None
    date_to: date | None
    items: list[RankingRow]
    source: Source


class CpvDivision(Answer):
    code: str = Field(description="The first two digits of a CPV code, e.g. 45.")
    name: str | None = Field(description="SEAP's name for the division, where a row gives it.")
