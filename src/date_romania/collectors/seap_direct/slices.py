"""Cutting a day into queries that each fit under SEAP's cap, and fetching them."""

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta

from date_romania.collectors.http import PoliteClient
from date_romania.sources import SEAP_DIRECT

log = logging.getLogger(__name__)

LIST_URL = "https://e-licitatie.ro/api-pub/DirectAcquisitionCommon/GetDirectAcquisitionList/"
HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Referer": SEAP_DIRECT.list_url,
}

CAP = 2000
# A busy day takes a few hundred requests; far beyond that, the filters have stopped working.
MAX_REQUESTS_PER_DAY = 3000

# The states a finished purchase can be in (the site's own filter offers exactly these):
# 3 refused by supplier, 4 not answered by supplier, 6 refused by buyer, 7 accepted,
# 8 not answered by buyer.
STATES = (3, 4, 6, 7, 8)
# Where the supplier said no or nothing, the buyer never got a deadline to decide.
STATES_WITHOUT_CA_DEADLINE = (3, 4)
CONTRACT_TYPES = (1, 2, 3)  # goods, services, works
# All divisions of the CPV 2008 vocabulary (first two digits of a code).
_CPV_DIVISIONS = (
    "03 09 14 15 16 18 19 22 24 30 31 32 33 34 35 37 38 39 41 42 43 44 "
    "45 48 50 51 55 60 63 64 65 66 70 71 72 73 75 76 77 79 80 85 90 92 98"
)
CPV_DIVISIONS = tuple(_CPV_DIVISIONS.split())

DateRange = tuple[date | None, date | None]
OPEN: DateRange = (None, None)


class SeapError(RuntimeError):
    pass


def _iso(day: date) -> str:
    return f"{day.isoformat()}T00:00:00.000Z"


def _split_range(span: DateRange, anchor: date) -> list[DateRange]:
    """Halve a date range (both ends inclusive); an open end is cut off in 30-day steps.

    Returns [] when the range cannot or should not be split: a single day, or an open end
    already a year away from `anchor`.
    """
    low, high = span
    one = timedelta(days=1)
    far = 365 * one
    if low is None and high is None:
        # Deadlines fall within days of the finalization date.
        return [(None, anchor - one), (anchor, anchor + 7 * one), (anchor + 8 * one, None)]
    if low is None:
        return [] if high < anchor - far else [(None, high - 30 * one), (high - 29 * one, high)]
    if high is None:
        return [] if low > anchor + far else [(low, low + 29 * one), (low + 30 * one, None)]
    if low == high:
        return []
    middle = low + (high - low) // 2
    return [(low, middle), (middle + one, high)]


@dataclass(frozen=True)
class Slice:
    """One query: a finalization day, narrowed by the filters set so far."""

    day: date
    state: int | None = None
    contract_type: int | None = None
    ca_deadline: DateRange = OPEN
    supplier_deadline: DateRange = OPEN
    multiple: bool | None = None
    eu_funded: bool | None = None
    cpv: str | None = None

    def request(self, page_size: int) -> dict:
        body: dict = {
            "pageSize": page_size,
            "pageIndex": 0,
            "showOngoingDa": False,
            "finalizationDateStart": _iso(self.day),
            "finalizationDateEnd": _iso(self.day),
        }
        optional = {
            "sysDirectAcquisitionStateId": self.state,
            "sysAcquisitionContractTypeId": self.contract_type,
            "caDecisionDeadlineStart": self.ca_deadline[0] and _iso(self.ca_deadline[0]),
            "caDecisionDeadlineEnd": self.ca_deadline[1] and _iso(self.ca_deadline[1]),
            "supplierDecisionDeadlineStart": self.supplier_deadline[0]
            and _iso(self.supplier_deadline[0]),
            "supplierDecisionDeadlineEnd": self.supplier_deadline[1]
            and _iso(self.supplier_deadline[1]),
            "isMultipleDa": self.multiple,
            "isEuFunded": self.eu_funded,
            "cpvCodeText": self.cpv,
        }
        body.update({key: value for key, value in optional.items() if value is not None})
        return body

    def children(self) -> list["Slice"]:
        """The next finer slices, which together hold every row of this one; [] at the end.

        State and contract type come first because they split exactly. The deadline filters
        skip rows that have no deadline, so states 3 and 4, which have no CA deadline, are
        never split by it; `parse_page` counts rows that lack a deadline anywhere else. The
        CPV filter matches its text anywhere in the code, so its slices overlap; rows are
        deduplicated by id on load.
        """
        if self.state is None:
            return [replace(self, state=state) for state in STATES]
        if self.contract_type is None:
            return [replace(self, contract_type=kind) for kind in CONTRACT_TYPES]
        if self.state not in STATES_WITHOUT_CA_DEADLINE and (
            spans := _split_range(self.ca_deadline, self.day)
        ):
            return [replace(self, ca_deadline=span) for span in spans]
        if spans := _split_range(self.supplier_deadline, self.day):
            return [replace(self, supplier_deadline=span) for span in spans]
        if self.multiple is None:
            return [replace(self, multiple=flag) for flag in (True, False)]
        if self.eu_funded is None:
            return [replace(self, eu_funded=flag) for flag in (True, False)]
        if self.cpv is None:
            return [replace(self, cpv=division) for division in CPV_DIVISIONS]
        if len(self.cpv) < 8:
            return [replace(self, cpv=self.cpv + digit) for digit in "0123456789"]
        return []


@dataclass(frozen=True)
class Page:
    slice: Slice
    request_body: str
    content: bytes
    data: dict
    # True when the slice is over the cap and cannot be split further: rows are missing.
    truncated: bool = False


Fetch = Callable[[Slice, int], Page]


def fetch(client: PoliteClient, sl: Slice, page_size: int) -> Page:
    body = json.dumps(sl.request(page_size), separators=(",", ":"))
    response = client.request("POST", LIST_URL, content=body, headers=HEADERS)
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise SeapError(f"unexpected answer to {body}: {response.text[:200]!r}")
    return Page(sl, body, response.content, data)


def is_capped(data: dict) -> bool:
    return bool(data.get("searchTooLong")) or data.get("total", 0) >= CAP


def iter_pages(
    day: date, fetch_page: Fetch, max_requests: int = MAX_REQUESTS_PER_DAY
) -> Iterator[Page]:
    """Yield full pages that together hold every purchase finalized on `day`.

    Each slice is first probed with one row, so an over-full slice costs a small request.
    """
    requests = 0

    def call(sl: Slice, page_size: int) -> Page:
        nonlocal requests
        requests += 1
        if requests > max_requests:
            raise SeapError(f"{day}: more than {max_requests} requests, giving up")
        return fetch_page(sl, page_size)

    todo = [Slice(day)]
    while todo:
        sl = todo.pop()
        probe = call(sl, 1)
        if not is_capped(probe.data):
            if not probe.data.get("total"):
                continue
            page = call(sl, CAP)
            if not is_capped(page.data):
                if len(page.data["items"]) != page.data.get("total"):
                    log.warning(
                        "%s: %d rows for a total of %s",
                        sl,
                        len(page.data["items"]),
                        page.data.get("total"),
                    )
                yield page
                continue
        children = sl.children()
        if children:
            todo.extend(reversed(children))
            continue
        log.warning("%s: over the cap of %d and cannot be split further", sl, CAP)
        yield replace(call(sl, CAP), truncated=True)
