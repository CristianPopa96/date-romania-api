"""The patterns of the rankings: purchases just under the limit."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from date_romania.api.schemas.common import EntityRef, Source


class NearLimitPurchase(BaseModel):
    id: int
    code: str | None
    name: str | None
    finalized_at: datetime | None
    value: float = Field(description="Closing value in lei without VAT.")


class NearLimitPair(BaseModel):
    """One buyer and one supplier with repeated accepted purchases just under a limit."""

    buyer: EntityRef
    supplier: EntityRef
    contract_type: int = Field(description="1 goods, 2 services, 3 works.")
    limit: float = Field(description="The legal limit for that type, in lei without VAT.")
    purchases: int
    value: float
    items: list[NearLimitPurchase] = Field(description="The purchases, oldest first.")


class NearLimitRule(BaseModel):
    share: float = Field(description="A value from this share of the limit up to it is near it.")
    repeats: int = Field(description="Purchases a pair needs to be listed.")
    limits: dict[int, float] = Field(description="The limit of each contract type.")


class NearLimitPattern(BaseModel):
    rule: NearLimitRule
    first_day: date | None = Field(description="The first day of a purchase checked.")
    last_day: date | None = Field(description="The last day of a purchase checked.")
    pairs: int = Field(description="Every pair that matches, beyond the ones listed.")
    items: list[NearLimitPair]
    checked: int = Field(
        description="Accepted purchases of known contract type: the ones that were checked."
    )
    accepted_total: int = Field(description="Accepted purchases, checked or not.")
    unknown_type: int = Field(
        description="Accepted purchases of unknown contract type, which cannot be checked."
    )
    source: Source
