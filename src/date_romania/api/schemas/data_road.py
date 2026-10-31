"""The road of the data, for the sources page: what is kept, read, tied and shown."""

from pydantic import Field

from date_romania.api.schemas.common import Answer


class Counted(Answer):
    key: str = Field(description="A table ('direct_purchase'), or a kind of project ('AS').")
    count: int


class LinkCount(Answer):
    rule: str = Field(
        description="What is tied to what: 'eu-beneficiary' (an EU project to its "
        "beneficiary), 'anghel-saligny-contract' (a payment to a SEAP contract), "
        "'eu-seap' (a SEAP record to an EU project), 'pnrr-payment-contract' (a PNRR "
        "payment to its contract), 'entity-place' (an institution or company to its UAT)."
    )
    method: str = Field(description="How, as the rule names it ('cui-in-list', 'smis-in-text').")
    confidence: str | None = Field(description="sure, probable or possible; null for a fact.")
    count: int


class DataRoad(Answer):
    """Each step, in figures: the answers kept whole, the rows read from them, the links
    made between them, and the projects the site shows."""

    documents: int = Field(description="Answers and files kept whole in the raw store.")
    stored_bytes: int
    rejected_rows: int = Field(description="Rows the parsers could not read, logged.")
    read: list[Counted] = Field(description="Rows read, by table.")
    links: list[LinkCount]
    entities: int = Field(description="Institutions and companies held.")
    projects: list[Counted] = Field(description="Projects shown, by kind of programme.")
    reach: list[Counted] = Field(
        description="Projects by how far their money is followed ('beneficiary', "
        "'payments', 'purchases', 'companies')."
    )
