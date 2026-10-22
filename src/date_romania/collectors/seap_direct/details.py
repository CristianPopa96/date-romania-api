"""The detail of one direct purchase: its lines, payment and delivery conditions.

One request per purchase, so only some are asked for: the accepted ones of
`MIN_VALUE` lei or more, newest first (Crispy, 22.10.2026). The rest show as not
collected yet.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.collectors.http import PoliteClient
from date_romania.models import DirectPurchase, DirectPurchaseDetail
from date_romania.sources import SEAP_DIRECT

# Ends with the purchase id.
DETAIL_URL = "https://e-licitatie.ro/api-pub/PublicDirectAcquisition/getView/"
MIN_VALUE = Decimal(100_000)
# A run stops after this many failures in a row: SEAP is refusing, not one purchase.
MAX_FAILURES_IN_A_ROW = 20


class SeapError(RuntimeError):
    pass


@dataclass(frozen=True)
class Answer:
    url: str
    content: bytes
    data: dict


def fetch(client: PoliteClient, purchase_id: int) -> Answer:
    """SEAP answers 403 unless the request names the purchase's public page."""
    url = f"{DETAIL_URL}{purchase_id}"
    response = client.request(
        "GET", url, headers={"Referer": SEAP_DIRECT.record_url.format(id=purchase_id)}
    )
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise SeapError(f"unexpected answer from {url}: {response.text[:200]!r}")
    return Answer(url, response.content, data)


def due(session: Session, limit: int | None = None) -> list[int]:
    """The purchases whose detail is wanted and not held, newest first."""
    return list(
        session.scalars(
            select(DirectPurchase.id)
            .where(
                money.accepted,
                DirectPurchase.closing_value >= MIN_VALUE,
                DirectPurchase.id.not_in(select(DirectPurchaseDetail.purchase_id)),
            )
            .order_by(DirectPurchase.published_at.desc().nulls_last(), DirectPurchase.id.desc())
            .limit(limit)
        )
    )
