"""The contract list as a file."""

from collections.abc import Iterable

from fastapi.responses import StreamingResponse

from date_romania.api.routes.common import cell, csv_file
from date_romania.api.schemas import Contract


def contracts_csv(contracts: Iterable[Contract]) -> StreamingResponse:
    """The list as a file; every row names its notice and where it was read."""
    header = [
        "notice_no",
        "contract_no",
        "signed_at",
        "kind",
        "title",
        "buyer_cui",
        "buyer",
        "winner_cuis",
        "winners",
        "value_ron_without_vat",
        "source",
        "source_url",
        "fetched_at",
    ]
    rows = (
        [
            cell(contract.notice_no),
            cell(contract.contract_no),
            contract.signed_at and contract.signed_at.isoformat(),
            contract.kind,
            cell(contract.title or contract.notice_title),
            contract.buyer and contract.buyer.cui,
            cell(contract.buyer.name if contract.buyer else contract.buyer_text),
            "; ".join(str(w.supplier.cui) for w in contract.winners if w.supplier),
            cell(
                "; ".join(
                    (w.supplier.name if w.supplier else w.text) or "" for w in contract.winners
                )
            ),
            contract.value,
            contract.source.publisher,
            contract.source.url,
            contract.source.fetched_at and contract.source.fetched_at.isoformat(),
        ]
        for contract in contracts
    )
    return csv_file(header, rows, "contracte.csv")
