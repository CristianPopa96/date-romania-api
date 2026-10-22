"""The patterns of the rankings: purchases just under the limit."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from date_romania.api.schemas.common import Answer, EntityRef, Source

# SEAP's contract types: 1 goods, 2 services, 3 works.
ContractType = Literal[1, 2, 3]


class NearLimitPurchase(Answer):
    id: int
    code: str | None
    name: str | None
    finalized_at: datetime | None
    value: float = Field(description="Closing value in lei without VAT.")


class NearLimitPair(Answer):
    """One buyer and one supplier with repeated accepted purchases just under a limit."""

    buyer: EntityRef
    supplier: EntityRef
    contract_type: ContractType = Field(description="1 goods, 2 services, 3 works.")
    limit: float = Field(description="The legal limit for that type, in lei without VAT.")
    purchases: int
    value: float
    items: list[NearLimitPurchase] = Field(description="The purchases, oldest first.")


class NearLimitRule(Answer):
    share: float = Field(description="A value from this share of the limit up to it is near it.")
    repeats: int = Field(description="Purchases a pair needs to be listed.")
    limits: dict[int, float] = Field(description="The limit of each contract type.")


class NearLimitPattern(Answer):
    rule: NearLimitRule
    first_day: date | None = Field(description="The first day of a purchase checked.")
    last_day: date | None = Field(description="The last day of a purchase checked.")
    pairs: int = Field(description="Every pair that matches, beyond the ones listed.")
    items: list[NearLimitPair]
    checked: int = Field(
        description="Accepted purchases of known contract type, outside Annex 2: the ones "
        "that were checked."
    )
    accepted_total: int = Field(description="Accepted purchases, checked or not.")
    unknown_type: int = Field(
        description="Accepted purchases of unknown contract type outside Annex 2, which cannot "
        "be checked. `checked`, `unknown_type` and `annex_2` add up to `accepted_total`."
    )
    annex_2: int = Field(
        description="Accepted purchases of services in Annex 2 of Law 98/2016 (by CPV code), "
        "which have no direct purchase limit to be near."
    )
    source: Source
