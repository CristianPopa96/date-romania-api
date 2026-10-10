"""Writing parsed rows to the database."""

from itertools import batched

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from date_romania.collectors.seap_direct.parse import PARSER_VERSION, Parsed
from date_romania.models import DirectPurchase, Entity


def load(session: Session, parsed: Parsed, source_document_id: int) -> None:
    """Upsert the parsed rows. New entities are added; known ones keep their name."""
    if parsed.entities:
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
                    for cui, (name, kind) in parsed.entities.items()
                ]
            )
            .on_conflict_do_nothing()
        )
        buyers = [cui for cui, (_, kind) in parsed.entities.items() if kind == "authority"]
        if buyers:
            session.execute(
                update(Entity)
                .where(Entity.cui.in_(buyers), Entity.kind != "authority")
                .values(kind="authority")
            )
    for rows in batched(parsed.purchases, 500):
        statement = insert(DirectPurchase).values(
            [
                {**row, "source_document_id": source_document_id, "parser_version": PARSER_VERSION}
                for row in rows
            ]
        )
        changed = {
            column.name: statement.excluded[column.name]
            for column in DirectPurchase.__table__.columns
            if column.name not in ("id", "updated_at")
        }
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[DirectPurchase.id], set_={**changed, "updated_at": func.now()}
            )
        )
