"""The rule every source follows when it names an institution or a company."""

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from date_romania.models import Entity
from date_romania.text import plain

# Words that make a beneficiary public, or a company, in the ministries' free text.
_PUBLIC = (
    "UAT",
    "INSTITUTI",
    "INVATAMANT",
    "UNIVERSITAT",
    "SPITAL",
    "SANATORIU",
    "AUTORITATE",
    "ADMINISTRATI",
    "MINISTER",
    "DIRECTIE",
    "INSTITUT",
    "GRADINITA",
    "AUTORITATI",
)
_PUBLIC_EXACT = {"DSP", "SAJ", "CJ", "INCD", "IP", "ASSMB", "MS", "MAI", "CNAS", "SRI", "CCD"}
_COMPANY = (
    "IMM",
    "INTREPRINDERE",
    "SOCIETATE",
    "COMPANIE",
    "COOPERATIVA",
    "MEDIC FAMILIE",
)
_COMPANY_EXACT = {
    "SRL",
    "S R L",
    "SA",
    "S A",
    "SC",
    "S C",
    "PFA",
    "P F A",
    "II",
    "I I",
    "I F",
    "RA",
    "R A",
    "CMI",
    "PJ",
    "MICROINTREPRINDERE",
}


def upsert(session: Session, entities: dict[int, tuple[str, str]], source_document_id: int) -> None:
    """Add the entities not seen before, given as cui -> (name, kind).

    Known ones keep their name. Whoever buys with public money becomes an authority, even
    if it was first seen as a company.
    """
    if not entities:
        return
    session.execute(
        insert(Entity)
        .values(
            [
                {
                    "cui": cui,
                    "name": name,
                    "kind": kind,
                    "source_document_id": source_document_id,
                }
                for cui, (name, kind) in entities.items()
            ]
        )
        .on_conflict_do_nothing()
    )
    buyers = [cui for cui, (_, kind) in entities.items() if kind == "authority"]
    if buyers:
        session.execute(
            update(Entity)
            .where(Entity.cui.in_(buyers), Entity.kind != "authority")
            .values(kind="authority")
        )


def kind_of(beneficiary_type: str | None) -> str:
    """The entity kind a ministry's own word for a beneficiary suggests: 'authority' only when it is
    clearly public, 'company' when clearly a business, else 'other'."""
    words = plain(beneficiary_type)
    if words in _PUBLIC_EXACT or any(word in words for word in _PUBLIC):
        return "authority"
    if words in _COMPANY_EXACT or any(word in words for word in _COMPANY):
        return "company"
    return "other"
