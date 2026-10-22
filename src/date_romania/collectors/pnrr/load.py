"""Writing one edition to the database: every PNRR table replaced by it."""

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from date_romania import entities
from date_romania.collectors.pnrr.parse import PARSER_VERSION, Parsed, tie
from date_romania.models import (
    PnrrContract,
    PnrrContractLine,
    PnrrEdition,
    PnrrMeasure,
    PnrrPayment,
    PnrrTopRecipient,
)

BATCH = 5000


def _insert(session: Session, model, rows: list[dict]) -> None:
    for start in range(0, len(rows), BATCH):
        session.execute(insert(model), rows[start : start + BATCH])


def load(session: Session, parsed: dict[str, tuple[Parsed, int]]) -> None:
    """`parsed` maps each endpoint to what was read from it and its document id.

    The tables hold one edition: they are emptied and filled again, in one transaction.
    """
    stamp = {"parser_version": PARSER_VERSION}

    def rows(endpoint: str, name: str) -> list[dict]:
        found, doc = parsed[endpoint]
        return [{**row, **stamp, "source_document_id": doc} for row in getattr(found, name)]

    # Contracts first: the kind of entity they suggest is better than a payment's.
    for endpoint in ("progres_tehnic_proiecte", "plati_pnrr"):
        found, doc = parsed[endpoint]
        entities.upsert(session, found.entities, doc)

    contracts, _ = parsed["progres_tehnic_proiecte"]
    payments = rows("plati_pnrr", "payments")
    tie(payments, contracts.contracts, contracts.lines)

    for model in (
        PnrrPayment,
        PnrrContractLine,
        PnrrContract,
        PnrrMeasure,
        PnrrTopRecipient,
        PnrrEdition,
    ):
        session.execute(delete(model))
    _insert(session, PnrrEdition, rows("indicatori_total", "totals"))
    _insert(session, PnrrMeasure, rows("masuri", "measures"))
    _insert(session, PnrrContract, rows("progres_tehnic_proiecte", "contracts"))
    # A line has no document or parser of its own: its contract's.
    _insert(session, PnrrContractLine, contracts.lines)
    _insert(session, PnrrPayment, payments)
    _insert(session, PnrrTopRecipient, rows("top_beneficiari", "top"))
