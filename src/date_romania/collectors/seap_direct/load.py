"""Writing parsed rows to the database."""

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from date_romania import entities
from date_romania.collectors.seap_direct.parse import (
    DETAIL_PARSER_VERSION,
    PARSER_VERSION,
    Parsed,
)
from date_romania.db import upsert_rows
from date_romania.models import DirectPurchase, DirectPurchaseDetail, DirectPurchaseItem


def load(session: Session, parsed: Parsed, source_document_id: int) -> None:
    """Upsert the parsed rows. New entities are added; known ones keep their name.

    A purchase read again by a query that did not filter by type keeps the type it had.
    The lines of a purchase are replaced as a whole.
    """
    entities.upsert(session, parsed.entities, source_document_id)
    upsert_rows(
        session,
        DirectPurchase,
        [
            {**row, "source_document_id": source_document_id, "parser_version": PARSER_VERSION}
            for row in parsed.purchases
        ],
        keep=("contract_type_id",),
    )
    upsert_rows(
        session,
        DirectPurchaseDetail,
        [
            {
                **row,
                "source_document_id": source_document_id,
                "parser_version": DETAIL_PARSER_VERSION,
            }
            for row in parsed.details
        ],
        index_elements=("purchase_id",),
    )
    if parsed.items_of is not None:
        session.execute(
            delete(DirectPurchaseItem).where(DirectPurchaseItem.purchase_id == parsed.items_of)
        )
    if parsed.items:
        session.execute(
            insert(DirectPurchaseItem),
            [{**row, "source_document_id": source_document_id} for row in parsed.items],
        )
