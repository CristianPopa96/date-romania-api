"""SEAP direct purchases (achiziții directe), from the public list on e-licitatie.ro.

The API is unofficial. It returns at most 2,000 rows per query, will not page past them,
and ignores the time of day in its date filters, while a working day has well over 10,000
purchases. So one day is split by the filters that do work until every slice fits.
"""

import json
import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import batched

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, store_document
from date_romania.cui import parse_cui
from date_romania.models import DirectPurchase, Entity, SourceDocument
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = "seap-direct"
PARSER_VERSION = 2

LIST_URL = "https://e-licitatie.ro/api-pub/DirectAcquisitionCommon/GetDirectAcquisitionList/"
HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Referer": "https://e-licitatie.ro/pub/direct-acquisitions/list/1",
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
CPV_DIVISIONS = tuple(
    f"{division:02d}"
    for division in (
        *(3, 9, 14, 15, 16, 18, 19, 22, 24, 30, 31, 32, 33, 34, 35, 37, 38, 39, 41, 42, 43, 44),
        *(
            45,
            48,
            50,
            51,
            55,
            60,
            63,
            64,
            65,
            66,
            70,
            71,
            72,
            73,
            75,
            76,
            77,
            79,
            80,
            85,
            90,
            92,
            98,
        ),
    )
)

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


_PARTY = re.compile(r"\s*(?:RO?)?\s*(\d{2,10})\s+(.*)", re.IGNORECASE | re.DOTALL)
# A personal numeric code: sole traders are sometimes listed under it instead of a CUI.
_CNP = re.compile(r"\b[1-9]\d{12}\b")


_CNP_KEY = "279146358279"


def is_cnp(digits: str) -> bool:
    """True for 13 digits with a possible birth date and the right control digit."""
    if not (1 <= int(digits[3:5]) <= 12 and 1 <= int(digits[5:7]) <= 31):
        return False
    control = sum(int(d) * int(k) for d, k in zip(digits, _CNP_KEY, strict=False)) % 11
    return (1 if control == 10 else control) == int(digits[12])


def mask_cnp(text: str | None, checked: bool = False) -> str | None:
    """Hide personal numeric codes (GDPR); the name of a sole trader stays.

    Where a party is named, any 13-digit number is hidden. In free text most such numbers
    are barcodes and permit numbers, so `checked` hides only those that are valid codes.
    """
    if not text:
        return text
    return _CNP.sub(
        lambda found: "[CNP]" if not checked or is_cnp(found.group()) else found.group(), text
    )


def split_party(text: str | None) -> tuple[int | None, str | None]:
    """Split SEAP's 'CUI NAME' text, e.g. 'RO 8574866 ALMERA INTERNATIONAL' or 'R 361684 BNR'."""
    text = (text or "").strip()
    match = _PARTY.fullmatch(text)
    if not match:
        return None, text or None
    return parse_cui(match.group(1)), match.group(2).strip() or None


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _money(value: float | int | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@dataclass
class Parsed:
    purchases: list[dict] = field(default_factory=list)
    # cui -> (name, kind)
    entities: dict[int, tuple[str, str]] = field(default_factory=dict)
    # (item, reason) for rows that could not be read at all
    rejected: list[tuple[object, str]] = field(default_factory=list)
    invalid_cuis: int = 0
    # Rows without a deadline where one is expected: a slice split by deadline would miss them.
    missing_deadlines: int = 0


def parse_page(data: dict) -> Parsed:
    """Turn one list response into rows; a later copy of the same purchase replaces an earlier."""
    parsed = Parsed()
    by_id: dict[int, dict] = {}
    for item in data.get("items", []):
        try:
            state = item.get("sysDirectAcquisitionState") or {}
            cpv_code, _, cpv_name = (item.get("cpvCode") or "").partition(" - ")
            buyer_cui, buyer_name = split_party(item.get("contractingAuthority"))
            supplier_cui, supplier_name = split_party(item.get("supplier"))
            row = {
                "id": int(item["directAcquisitionId"]),
                "code": item.get("uniqueIdentificationCode"),
                "name": mask_cnp(item.get("directAcquisitionName"), checked=True),
                "state_id": state.get("id"),
                "state": state.get("text"),
                "cpv_code": cpv_code.strip() or None,
                "cpv_name": cpv_name.strip() or None,
                "buyer_cui": buyer_cui,
                "buyer_text": mask_cnp(item.get("contractingAuthority")),
                "supplier_cui": supplier_cui,
                "supplier_text": mask_cnp(item.get("supplier")),
                "published_at": _when(item.get("publicationDate")),
                "finalized_at": _when(item.get("finalizationDate")),
                "estimated_value_ron": _money(item.get("estimatedValueRon")),
                "closing_value": _money(item.get("closingValue")),
            }
        except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
            parsed.rejected.append((item, repr(exc)))
            continue
        by_id[row["id"]] = row
        parsed.invalid_cuis += (buyer_cui is None) + (supplier_cui is None)
        parsed.missing_deadlines += item.get("supplierDecisionDeadline") is None or (
            item.get("caDecisionDeadline") is None
            and row["state_id"] not in STATES_WITHOUT_CA_DEADLINE
        )
        if supplier_cui is not None and supplier_cui not in parsed.entities:
            parsed.entities[supplier_cui] = (supplier_name or f"CUI {supplier_cui}", "company")
        if buyer_cui is not None:
            # Whoever buys with public money is listed as an authority, even if it also sells.
            parsed.entities[buyer_cui] = (buyer_name or f"CUI {buyer_cui}", "authority")
    parsed.purchases = list(by_id.values())
    return parsed


def load(session: Session, parsed: Parsed, source_document_id: int) -> None:
    """Upsert the parsed rows. New entities are added; known ones keep their name."""
    if parsed.entities:
        session.execute(
            insert(Entity)
            .values(
                [
                    {
                        "cui": cui,
                        "name": name,
                        "kind": kind,
                        "source_document_id": source_document_id,
                    }
                    for cui, (name, kind) in parsed.entities.items()
                ]
            )
            .on_conflict_do_nothing()
        )
        buyers = [cui for cui, (_, kind) in parsed.entities.items() if kind == "authority"]
        if buyers:
            session.execute(
                update(Entity)
                .where(Entity.cui.in_(buyers), Entity.kind != "authority")
                .values(kind="authority")
            )
    for rows in batched(parsed.purchases, 500):
        statement = insert(DirectPurchase).values(
            [
                {**row, "source_document_id": source_document_id, "parser_version": PARSER_VERSION}
                for row in rows
            ]
        )
        changed = {
            column.name: statement.excluded[column.name]
            for column in DirectPurchase.__table__.columns
            if column.name not in ("id", "updated_at")
        }
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[DirectPurchase.id], set_={**changed, "updated_at": func.now()}
            )
        )


def _parse_and_load(session: Session, data: dict, doc: SourceDocument) -> Parsed:
    parsed = parse_page(data)
    for item, reason in parsed.rejected:
        log.warning("source_document %d: rejected row %s: %.500r", doc.id, reason, item)
    load(session, parsed, doc.id)
    return parsed


def collect_day(session: Session, client: PoliteClient, day: date) -> int:
    """Fetch, store and load every direct purchase finalized on `day`; returns how many."""
    with job_run(session, JOB, day) as run:
        ids: set[int] = set()
        pages = truncated = invalid_cuis = missing_deadlines = 0
        for page in iter_pages(day, lambda sl, size: fetch(client, sl, size)):
            doc = store_document(
                session, SOURCE, LIST_URL, page.content, page.request_body, "application/json"
            )
            parsed = _parse_and_load(session, page.data, doc)
            session.commit()
            ids.update(row["id"] for row in parsed.purchases)
            pages += 1
            truncated += page.truncated
            invalid_cuis += parsed.invalid_cuis
            missing_deadlines += parsed.missing_deadlines
        run.records = len(ids)
        if truncated:
            run.status = "partial"
            run.error = f"{truncated} slices stayed over the cap of {CAP}: the day is incomplete"
        if missing_deadlines:
            log.warning(
                "%s: %d rows lack a deadline where one is expected; "
                "slices split by deadline may have missed such rows",
                day,
                missing_deadlines,
            )
        log.info(
            "%s: %d purchases in %d pages, %d names without a valid CUI",
            day,
            len(ids),
            pages,
            invalid_cuis,
        )
    return len(ids)


def reparse(session: Session) -> int:
    """Rebuild the rows from the raw store, oldest file first, without calling SEAP."""
    docs = session.scalars(
        select(SourceDocument).where(SourceDocument.source == SOURCE).order_by(SourceDocument.id)
    ).all()
    for doc in docs:
        _parse_and_load(session, json.loads(get_raw(doc.storage_key)), doc)
        session.commit()
    return len(docs)
