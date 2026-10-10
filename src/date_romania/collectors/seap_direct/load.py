"""Writing parsed rows to the database."""

from sqlalchemy.orm import Session

from date_romania import entities
from date_romania.collectors.seap_direct.parse import PARSER_VERSION, Parsed
from date_romania.db import upsert_rows
from date_romania.models import DirectPurchase


def load(session: Session, parsed: Parsed, source_document_id: int) -> None:
    """Upsert the parsed rows. New entities are added; known ones keep their name."""
    entities.upsert(session, parsed.entities, source_document_id)
    upsert_rows(
        session,
        DirectPurchase,
        [
            {**row, "source_document_id": source_document_id, "parser_version": PARSER_VERSION}
            for row in parsed.purchases
        ],
    )
