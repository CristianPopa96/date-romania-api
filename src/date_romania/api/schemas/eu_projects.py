"""EU cohesion projects: the programmes held, a list of projects, one project.

A list gives what a project was worth and paid at its cut-off day, never the day of a
payment; the Health programme also publishes its payments one by one.
"""

from datetime import date
from typing import Literal

from pydantic import Field

from date_romania.api.schemas.awards import Contract
from date_romania.api.schemas.common import Answer, EntityRef, Source
from date_romania.api.schemas.purchases import Purchase

EuStatus = Literal["in_progress", "finished", "terminated"]
LinkConfidence = Literal["sure", "probable"]
# How it was tied (see eu_links.py).
LinkMethod = Literal["cui-in-list", "administration-name+place", "name+place", "company-name"]
# How a SEAP record was tied to a project (see eu_seap_links.py).
SeapLinkMethod = Literal["smis-in-text", "financing-number+buyer", "pnrr-measure+buyer"]


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
    method: LinkMethod | None


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


class SeapLink(Answer):
    cited: str = Field(
        description="What SEAP's text cites, as written: '341497', '12321/26.08.2024'; for "
        "pnrr-measure+buyer, the contract's measure it fits ('C10.I3'), or 'PNRR' when the "
        "buyer's only PNRR contract is tied with no measure cited."
    )
    method: SeapLinkMethod
    confidence: LinkConfidence = Field(description="Always probable: the buyer's own text.")


class SeapCompany(Answer):
    name: str
    entity: EntityRef | None = Field(description="Set when the company has a page.")


class EuSeapContract(SeapLink):
    contract: Contract


class EuSeapPurchase(SeapLink):
    purchase: Purchase


class EuSeapLinks(Answer):
    """The SEAP records whose text cites a project. Incomplete by nature: SEAP has no field
    for the project, and many buyers never write it."""

    contracts_total: int
    contracts: list[EuSeapContract] = Field(
        description="The contracts of the award notices tied, in a notice still in force, "
        "the newest first, one page of them. A framework agreement is a ceiling, never a sum "
        "spent."
    )
    notices: int = Field(description="The award notices tied, still in force.")
    companies: int = Field(
        description="Every company that won a tied contract or sold a tied purchase, told "
        "apart by CUI, or by name where SEAP gives none."
    )
    largest: SeapCompany | None = Field(
        description="The company with the most value across the tied records: contracts "
        "counted (never a framework agreement) and accepted purchases, added together. A "
        "member of an association is counted with the whole contract's value. Null when no "
        "tied record counts any value."
    )
    purchases: list[EuSeapPurchase] = Field(
        description="The accepted direct purchases tied, the newest first, all of them."
    )


class EuBeneficiaryProgramme(EuProgramme):
    by_name: int = Field(
        description="Of `projects`, those tied by name and place (probable): the list gives "
        "no CUI for them."
    )


class EuBeneficiaryPnrr(Answer):
    """A beneficiary's PNRR contracts and the payments it received, from one dashboard
    edition. The payments name the beneficiary and a measure, never the contract: they are
    counted for the beneficiary, not shared out among its contracts."""

    contracts: int = Field(description="0 when it was paid on a measure with no contract held.")
    total: float | None = Field(description="Lei, its contracts' values added up.")
    paid: float = Field(description="Lei paid to it on every measure.")
    payments: int
    first_day: date | None
    last_day: date | None
    edition: date = Field(description="The day of the dashboard edition held.")
    source: Source


class EuBeneficiaryFunds(Answer):
    """The EU money of one beneficiary, of both kinds, never added together: its cohesion
    projects by programme, each at its own list's day, and its PNRR contracts and
    payments. The projects and contracts themselves are listed by
    `/programmes/eu-funds/projects` and `/programmes/pnrr/contracts`, by `beneficiary`."""

    entity: EntityRef
    cohesion: list[EuBeneficiaryProgramme] = Field(
        description="Its projects in each programme, tied by eu_links.py, by the CUI in the "
        "list or by name; empty when none."
    )
    cohesion_source: Source | None = Field(description="Null when it has no project.")
    pnrr: EuBeneficiaryPnrr | None = Field(description="Null when it has no contract or payment.")
