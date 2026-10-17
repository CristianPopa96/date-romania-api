"""Readers' error reports and the published corrections."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from date_romania.api.schemas.common import Answer


class ReportIn(BaseModel):
    """What a reader says is wrong on a page of the site."""

    model_config = ConfigDict(str_strip_whitespace=True)

    page: str | None = Field(None, max_length=300, description="The page the report is about.")
    message: str = Field(min_length=10, max_length=4000, description="What is wrong.")
    evidence: str | None = Field(
        None, max_length=500, description="A link or a document that shows the right value."
    )


class ReportReceived(Answer):
    id: int


class Correction(Answer):
    """A report we checked and acted on: where, and what we changed, in our words."""

    page: str | None = Field(
        description="The address of the page on the site; null when the report named no such page."
    )
    correction: str
    corrected_on: date


class Corrections(Answer):
    items: list[Correction]
