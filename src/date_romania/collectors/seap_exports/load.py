"""Writing parsed export contracts to the database."""

from sqlalchemy import delete, func, insert
from sqlalchemy.dialects.postgresql import insert as upsert
from sqlalchemy.orm import Session

from date_romania.collectors.seap_exports.parse import PARSER_VERSION, Parsed
from date_romania.models import ExportBuyer, ExportContract


def load(session: Session, parsed: Parsed, source_document_id: int) -> None:
    """Replace the contracts read from one export as a whole.

    The exports give a contract no id of its own, so a row cannot be told from its copy
    in a later reading; the file is the unit.
    """
    session.execute(
        delete(ExportContract).where(ExportContract.source_document_id == source_document_id)
    )
    stamp = {"source_document_id": source_document_id, "parser_version": PARSER_VERSION}
    if parsed.contracts:
        session.execute(insert(ExportContract), [{**row, **stamp} for row in parsed.contracts])
    _load_buyers(session, parsed, source_document_id)


def _load_buyers(session: Session, parsed: Parsed, source_document_id: int) -> None:
    """Keep every buyer of the export. A county learned from one export stays when a
    later one does not give it."""
    rows = [
        {"cui": cui, "name": name, "county": county, "source_document_id": source_document_id}
        for cui, (name, county) in parsed.buyers.items()
    ]
    for start in range(0, len(rows), 1000):
        statement = upsert(ExportBuyer).values(rows[start : start + 1000])
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["cui"],
                set_={
                    "name": statement.excluded.name,
                    "county": func.coalesce(statement.excluded.county, ExportBuyer.county),
                    "source_document_id": statement.excluded.source_document_id,
                },
            )
        )
