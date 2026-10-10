"""The rule every source follows when it names an institution or a company."""

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from date_romania.models import Entity


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
