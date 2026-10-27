"""EU cohesion projects: the programmes held, a list of projects, one project.

A list gives what a project was worth and paid at its cut-off day, never the day of a
payment; the Health programme also publishes its payments one by one.
"""

from datetime import date
from typing import Literal

from pydantic import Field

from date_romania.api.schemas.common import Answer, EntityRef, Source

EuStatus = Literal["in_progress", "finished", "terminated"]
LinkConfidence = Literal["sure", "probable"]


class EuProgramme(Answer):
    code: str = Field(description="'POR', 'PEO', 'PoIDS'...")
    name: str
    period: str = Field(description="'2014-2020' or '2021-2027'.")
    projects: int
    total: float | None = Field(description="Lei, the projects' total value added up.")
    paid: float | None = Field(description="Lei paid up to `cut_off`; null when not published.")
    cut_off: date | None = Field(description="The day the programme's newest list describes.")


class EuFunds(Answer):
    """The programmes held. Their figures describe different days: never add them up."""

    programmes: list[EuProgramme]
    source: Source


class EuBeneficiary(Answer):
    name: str | None = Field(description="As the list writes it.")
    entity: EntityRef | None = Field(description="The entity it is tied to, when one is.")
    confidence: LinkConfidence | None = Field(
        description="sure: the list gives the tax ID; probable: tied by name and place."
    )


class EuProjectRow(Answer):
    smis: int
    programme: str
    title: str | None
    beneficiary: EuBeneficiary
    county: str | None = Field(description="As the list writes it.")
    total: float | None
    paid: float | None
    status: EuStatus | None
    status_written: str | None = Field(description="The status as the list writes it.")


class EuProjectPage(Answer):
    total: int
    items: list[EuProjectRow]


class EuPayment(Answer):
    paid_on: date | None
    amount: float
    kind: str | None = Field(description="'Plată', 'Prefinanțare'..., as published.")
    funding: str | None


class EuProject(EuProjectRow):
    programme_name: str
    period: str
    partners: str | None = Field(description="As the list writes them; never tied.")
    summary: str | None
    beneficiary_type: str | None
    locality: str | None
    starts_on: date | None
    ends_on: date | None
    cofinancing_rate: float | None = Field(description="The EU's share, from 0 to 1.")
    eu: float | None
    cut_off: date | None = Field(description="The day `paid` is counted up to.")
    payments: list[EuPayment] | None = Field(
        description="One by one, newest first; null where the programme does not publish them."
    )
    payments_source: Source | None
    source: Source
