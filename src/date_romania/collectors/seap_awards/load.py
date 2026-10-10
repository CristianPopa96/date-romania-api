"""Writing parsed rows to the database."""

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from date_romania import entities
from date_romania.collectors.seap_awards.parse import PARSER_VERSION, Parsed
from date_romania.db import upsert_rows
from date_romania.models import AwardContract, AwardNotice, AwardWinner


def load(session: Session, parsed: Parsed, source_document_id: int) -> None:
    """Upsert the parsed rows. The winners of a contract are replaced as a whole."""
    stamp = {"source_document_id": source_document_id, "parser_version": PARSER_VERSION}
    entities.upsert(session, parsed.entities, source_document_id)
    upsert_rows(session, AwardNotice, [{**row, **stamp} for row in parsed.notices])
    upsert_rows(session, AwardContract, [{**row, **stamp} for row in parsed.contracts])
    if parsed.contracts:
        session.execute(
            delete(AwardWinner).where(
                AwardWinner.contract_id.in_([row["id"] for row in parsed.contracts])
            )
        )
    if parsed.winners:
        session.execute(
            insert(AwardWinner),
            [{**row, "source_document_id": source_document_id} for row in parsed.winners],
        )
