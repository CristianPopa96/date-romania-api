"""Asking SEAP for the notices of a day and for the contracts of a notice."""

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

from date_romania.collectors.http import PoliteClient
from date_romania.sources import SEAP_AWARDS

log = logging.getLogger(__name__)

LIST_URL = "https://e-licitatie.ro/api-pub/NoticeCommon/GetCANoticeList/"
CONTRACTS_URL = "https://e-licitatie.ro/api-pub/C_PUBLIC_CANotice/GetCANoticeContracts/"
HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Referer": SEAP_AWARDS.list_url,
}

# The list stops at 3,000 rows and flags it with `searchTooLong`.
CAP = 3000
PAGE_SIZE = 500
CONTRACTS_PAGE_SIZE = 200


class SeapError(RuntimeError):
    pass


@dataclass(frozen=True)
class Page:
    url: str
    request_body: str
    content: bytes
    data: dict
    # True when the day has more notices than the list will give: rows are missing.
    truncated: bool = False


def _post(client: PoliteClient, url: str, request: dict) -> Page:
    body = json.dumps(request, separators=(",", ":"))
    response = client.request("POST", url, content=body, headers=HEADERS)
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise SeapError(f"unexpected answer to {body}: {response.text[:200]!r}")
    return Page(url, body, response.content, data)


def notice_pages(client: PoliteClient, day: date) -> Iterator[Page]:
    """Every list page of the notices published on `day`.

    SEAP reads the date in Romanian time and drops the time of day, so midnight UTC names
    the same day at both ends.
    """
    stamp = f"{day.isoformat()}T00:00:00.000Z"
    seen = index = 0
    while True:
        page = _post(
            client,
            LIST_URL,
            {
                # SEAP answers with an error if the two lists are left out.
                "sysNoticeTypeIds": [],
                "sortProperties": [],
                "pageSize": PAGE_SIZE,
                "pageIndex": index,
                "startPublicationDate": stamp,
                "endPublicationDate": stamp,
            },
        )
        total = page.data.get("total") or 0
        capped = bool(page.data.get("searchTooLong")) or total >= CAP
        seen += len(page.data["items"])
        done = not page.data["items"] or seen >= total
        if done and capped:
            log.warning("%s: over the cap of %d notices, the day is incomplete", day, CAP)
            page = Page(page.url, page.request_body, page.content, page.data, truncated=True)
        yield page
        if done:
            return
        index += 1


def contract_pages(client: PoliteClient, notice_id: int) -> Iterator[Page]:
    """Every page of the contracts of one notice; a notice with none gives one empty page."""
    seen = 0
    while True:
        page = _post(
            client,
            CONTRACTS_URL,
            {
                "caNoticeId": notice_id,
                # SEAP answers with an error if the sort list is left out.
                "sortOrder": [],
                "skip": seen,
                "take": CONTRACTS_PAGE_SIZE,
            },
        )
        yield page
        seen += len(page.data["items"])
        if not page.data["items"] or seen >= (page.data.get("total") or 0):
            return
