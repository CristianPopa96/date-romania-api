"""Writing parsed export contracts to the database."""

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from date_romania.collectors.seap_exports.parse import PARSER_VERSION, Parsed
from date_romania.models import ExportContract


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
