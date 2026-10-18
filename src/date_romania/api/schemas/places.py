"""Places: the counties, a county, one UAT (a commune, town, municipality or Bucharest
sector) and a search for them. Each figure names its own period; none is added to
another (design round 8)."""

from datetime import date

from pydantic import Field

from date_romania.api.schemas.budget import LocalBudgetOut, ProgrammePayments
from date_romania.api.schemas.common import Answer, EntityRef, Period, PlaceRef, Source
from date_romania.api.schemas.programmes import Match


class Population(Answer):
    people: int
    on: date = Field(description="1 January of the year counted.")


class Capital(Answer):
    """Capital spending executed in a year, by town halls (and a county's council)."""

    amount: float
    year: int
    places: int = Field(description="How many budgets it is added up from.")
    source: Source


class PlaceContracts(Answer):
    """Contracts signed in the period held by every buyer located in the place."""

    value: float
    contracts: int
    buyers: int
    period: Period
    source: Source


class SupplierCounties(Answer):
    """The contract value of `PlaceContracts` by where its winners are, after ANAF. An
    association counts as from the county only when all its members are; one with
    members in and out of it is counted apart, and no member stands for it."""

    county: str
    local: float = Field(description="Won by suppliers, or associations, all in the county.")
    mixed: float = Field(description="Won by associations with members in and out of it.")
    elsewhere: float = Field(description="Won by suppliers outside it, or of no known county.")


class TopWinner(Answer):
    """One supplier, or one association of suppliers, and what it won from the place's
    buyers. An association is one row with its whole value, never split."""

    members: list[EntityRef]
    counties: list[str | None] = Field(description="Each member's county, in `members`' order.")
    value: float
    contracts: int


class LocalProject(Answer):
    """An Anghel Saligny project of the town hall."""

    id: int
    investment: str | None
    builder: EntityRef | None
    builder_text: str | None
    progress: str | None = Field(description="As the town hall typed it in the latest file.")
    paid: float
    payments: int
    match: Match


class LocalInstitution(Answer):
    entity: EntityRef
    town_hall: bool
    contract_value: float
    contracts: int


class PlaceFigures(Answer):
    population: Population | None
    programme_payments: ProgrammePayments | None
    capital: Capital | None
    contracts: PlaceContracts
    supplier_counties: SupplierCounties
    top_winners: list[TopWinner]


class Locality(Answer):
    """One UAT. Bucharest lists its sectors in `parts`."""

    place: PlaceRef
    town_hall: EntityRef | None = Field(description="Its town hall, when held.")
    parts: list[PlaceRef]
    localities: list[str] = Field(
        description="The names of its villages and component localities, in SIRUTA's order."
    )
    figures: PlaceFigures
    budget: LocalBudgetOut | None = Field(description="The town hall's latest budget held.")
    projects: list[LocalProject]
    institutions: list[LocalInstitution] = Field(description="Every institution held there.")


class CountyUat(Answer):
    place: PlaceRef
    population: int | None
    capital: float | None = Field(description="Capital spending in the county's budget year.")
    contract_value: float
    contracts: int


class County(Answer):
    """A county, its figures added up over its UATs and its council."""

    place: PlaceRef
    council: EntityRef | None
    figures: PlaceFigures
    capital_year: int | None = Field(description="The budget year of the UATs' capital spending.")
    uats: list[CountyUat]


class CountyRow(Answer):
    place: PlaceRef
    uats: int
    population: int | None


class Counties(Answer):
    items: list[CountyRow]


class PlaceHit(Answer):
    """A UAT found by its name or by the name of one of its villages."""

    place: PlaceRef
    village: str | None = Field(description="The village searched for, when it is one.")


class PlaceResults(Answer):
    items: list[PlaceHit]
