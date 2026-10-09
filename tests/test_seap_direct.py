import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from date_romania.collectors.seap_direct import (
    CAP,
    CPV_DIVISIONS,
    Page,
    SeapError,
    Slice,
    _split_range,
    iter_pages,
    parse_page,
    split_party,
)

FIXTURE = Path(__file__).parent / "fixtures" / "seap_direct_page.json"
DAY = date(2026, 10, 6)


def test_split_party_reads_cui_and_name():
    assert split_party("RO 17886786 B.T.T. TOURS") == (17886786, "B.T.T. TOURS")
    assert split_party("4491342 Comuna Vladila") == (4491342, "Comuna Vladila")
    assert split_party("ro18288250 CERTSIGN") == (18288250, "CERTSIGN")
    assert split_party("R 361684 Banca Nationala a Romaniei") == (
        361684,
        "Banca Nationala a Romaniei",
    )
    assert split_party("R4245178 MUNICIPIUL TOPLITA") == (4245178, "MUNICIPIUL TOPLITA")


def test_split_party_keeps_text_without_a_valid_cui():
    assert split_party("17886787 WRONG CHECKSUM") == (None, "WRONG CHECKSUM")
    assert split_party("Some Foreign Ltd") == (None, "Some Foreign Ltd")
    assert split_party(None) == (None, None)


def test_parse_page_reads_the_saved_response():
    parsed = parse_page(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert len(parsed.purchases) == 7
    assert parsed.rejected == []
    assert parsed.invalid_cuis == 0

    row = next(row for row in parsed.purchases if row["id"] == 123157827)
    assert row["code"].startswith("DA")
    assert row["state_id"] == 7
    assert row["cpv_code"] == "60100000-9"
    assert row["cpv_name"].startswith("Servicii de transport")
    assert row["buyer_cui"] == 4981310
    assert row["buyer_text"] == "4981310 TEATRUL LUCEAFARUL IASI"
    assert row["supplier_cui"] == 17886786
    assert row["closing_value"] == Decimal("4950.0")
    assert row["finalized_at"].utcoffset() == timedelta(hours=3)

    assert parsed.entities[4981310] == ("TEATRUL LUCEAFARUL IASI", "authority")
    assert parsed.entities[17886786] == ("B.T.T. TOURS", "company")
    # Two purchases share a supplier and a buyer.
    assert len(parsed.entities) == 12


def test_parse_page_rejects_unreadable_rows_and_keeps_the_rest():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["items"][0] = {"directAcquisitionName": "no id"}
    data["items"][1]["finalizationDate"] = "not a date"
    data["items"][2]["supplier"] = "Some Foreign Ltd"
    parsed = parse_page(data)
    assert len(parsed.purchases) == 5
    assert len(parsed.rejected) == 2
    assert parsed.invalid_cuis == 1
    assert next(r for r in parsed.purchases if r["supplier_cui"] is None)["supplier_text"] == (
        "Some Foreign Ltd"
    )


def test_parse_page_masks_a_personal_numeric_code():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["items"][0]["supplier"] = "1234567890123 Popescu Ion PFA"
    row = parse_page(data).purchases[0]
    assert row["supplier_cui"] is None
    assert row["supplier_text"] == "[CNP] Popescu Ion PFA"


def test_parse_page_keeps_the_last_copy_of_a_repeated_purchase():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["items"].append({**data["items"][0], "directAcquisitionName": "later copy"})
    parsed = parse_page(data)
    assert len(parsed.purchases) == 7
    assert parsed.purchases[0]["name"] == "later copy"


def test_slice_request_sends_only_the_filters_that_are_set():
    assert Slice(DAY).request(1) == {
        "pageSize": 1,
        "pageIndex": 0,
        "showOngoingDa": False,
        "finalizationDateStart": "2026-10-06T00:00:00.000Z",
        "finalizationDateEnd": "2026-10-06T00:00:00.000Z",
    }
    body = Slice(
        DAY, state=7, ca_deadline=(None, date(2026, 10, 5)), multiple=False, cpv="15"
    ).request(CAP)
    assert body["sysDirectAcquisitionStateId"] == 7
    assert "caDecisionDeadlineStart" not in body
    assert body["caDecisionDeadlineEnd"] == "2026-10-05T00:00:00.000Z"
    assert body["isMultipleDa"] is False
    assert body["cpvCodeText"] == "15"
    assert "isEuFunded" not in body


def test_slice_children_always_run_out():
    for pick in (0, -1):
        sl, depth = Slice(DAY), 0
        while children := sl.children():
            sl, depth = children[pick], depth + 1
        assert len(sl.cpv) == 8
        assert depth < 60


def test_split_range_narrows_to_single_days():
    spans = [(DAY, DAY + timedelta(days=7))]
    days = []
    while spans:
        span = spans.pop()
        halves = _split_range(span, DAY)
        spans.extend(halves)
        if not halves:
            days.append(span)
    assert sorted(days) == [(DAY + timedelta(days=n),) * 2 for n in range(8)]


def _item(n: int, rng: random.Random, busy: bool) -> dict:
    """A purchase as the fake server sees it; `busy` rows all land in one crowded cell."""
    if busy:
        division = rng.choice(["15", "15", "15", "33", "30"])
        return {
            "id": n,
            "state": 7,
            "type": 1,
            "ca": DAY + timedelta(days=5),
            "su": DAY + timedelta(days=2),
            "multiple": False,
            "eu": False,
            "cpv": division + f"{rng.randrange(40):02d}0000",
        }
    state = rng.choice([3, 4, 6, 7, 8])
    return {
        "id": n,
        "state": state,
        "type": rng.choice([1, 2, 3]),
        "ca": None if state in (3, 4) else DAY + timedelta(days=rng.randrange(-40, 9)),
        "su": None if state in (3, 4) else DAY + timedelta(days=rng.randrange(-3, 40)),
        "multiple": rng.random() < 0.2,
        "eu": rng.random() < 0.1,
        "cpv": rng.choice(CPV_DIVISIONS) + f"{rng.randrange(10**6):06d}",
    }


def _in_range(value: date | None, span: tuple[date | None, date | None]) -> bool:
    low, high = span
    if low is None and high is None:
        return True
    return value is not None and (low is None or value >= low) and (high is None or value <= high)


def fake_seap(items: list[dict]):
    """Answer like the real list API: exact filters, a cap of 2,000 and no paging past it."""
    calls = []

    def fetch(sl: Slice, page_size: int) -> Page:
        calls.append((sl, page_size))
        found = [
            item
            for item in items
            if (sl.state is None or item["state"] == sl.state)
            and (sl.contract_type is None or item["type"] == sl.contract_type)
            and _in_range(item["ca"], sl.ca_deadline)
            and _in_range(item["su"], sl.supplier_deadline)
            and (sl.multiple is None or item["multiple"] == sl.multiple)
            and (sl.eu_funded is None or item["eu"] == sl.eu_funded)
            and (sl.cpv is None or sl.cpv in item["cpv"])
        ]
        data = {
            "total": min(len(found), CAP),
            "items": [{"directAcquisitionId": item["id"]} for item in found[:page_size]],
            "searchTooLong": len(found) > CAP,
        }
        return Page(sl, "{}", b"", data)

    return fetch, calls


def test_iter_pages_returns_every_purchase_of_a_busy_day():
    rng = random.Random(6)
    items = [_item(n, rng, busy=n < 9000) for n in range(14000)]
    fetch, calls = fake_seap(items)

    pages = list(iter_pages(DAY, fetch))

    seen = {row["directAcquisitionId"] for page in pages for row in page.data["items"]}
    assert seen == {item["id"] for item in items}
    assert not any(page.truncated for page in pages)
    assert all(len(page.data["items"]) < CAP for page in pages)
    assert len(calls) < 1000


def test_iter_pages_fetches_a_quiet_day_in_one_page():
    rng = random.Random(4)
    fetch, calls = fake_seap([_item(n, rng, busy=False) for n in range(99)])
    pages = list(iter_pages(DAY, fetch))
    assert [len(page.data["items"]) for page in pages] == [99]
    assert [size for _, size in calls] == [1, CAP]


def test_iter_pages_makes_no_full_request_for_an_empty_day():
    fetch, calls = fake_seap([])
    assert list(iter_pages(DAY, fetch)) == []
    assert [size for _, size in calls] == [1]


def test_iter_pages_marks_a_slice_it_cannot_split():
    rng = random.Random(1)
    items = [{**_item(n, rng, busy=True), "cpv": "15000000"} for n in range(CAP + 500)]
    fetch, _ = fake_seap(items)
    pages = list(iter_pages(DAY, fetch))
    assert [page.truncated for page in pages] == [True]
    assert pages[0].slice.cpv == "15000000"


def test_iter_pages_stops_when_the_filters_do_nothing():
    def fetch(sl: Slice, page_size: int) -> Page:
        return Page(sl, "{}", b"", {"total": CAP, "items": [], "searchTooLong": True})

    with pytest.raises(SeapError):
        list(iter_pages(DAY, fetch, max_requests=200))
