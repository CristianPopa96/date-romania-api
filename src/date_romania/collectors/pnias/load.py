"""Writing parsed payments to the database."""

from sqlalchemy.orm import Session

from date_romania.collectors.pnias.parse import PARSER_VERSION, Parsed
from date_romania.db import upsert_rows
from date_romania.models import PniasPayment


def load(session: Session, parsed: Parsed, source_document_id: int) -> None:
    """Upsert the payments, keyed by the ministry's number for the request."""
    stamp = {"source_document_id": source_document_id, "parser_version": PARSER_VERSION}
    # The place is found by `places.locate`, run after every load.
    rows = [{**row, **stamp, "siruta": None} for row in parsed.payments]
    upsert_rows(session, PniasPayment, rows, keep=("siruta",))
