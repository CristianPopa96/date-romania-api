"""Parsing and fetching award notices, from answers saved on 10 Oct 2026. No network."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.seap_awards.fetch import (
    CONTRACTS_URL,
    LIST_URL,
    SeapError,
    contract_pages,
    notice_pages,
)
from date_romania.collectors.seap_awards.parse import (
    parse_contracts,
    parse_notices,
    split_buyer,
    winner_cui,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def client(handler) -> PoliteClient:
    return PoliteClient(transport=httpx.MockTransport(handler), sleep=lambda seconds: None)


def test_split_buyer_reads_both_forms():
    assert split_buyer("4364349 - ADMINISTRATIA DOMENIULUI PUBLIC") == (
        4364349,
        "ADMINISTRATIA DOMENIULUI PUBLIC",
    )
    assert split_buyer("RO 2684940 - APA  CANAL  SIBIU SA") == (2684940, "APA  CANAL  SIBIU SA")
    assert split_buyer("RO11178217 - S.N. AEROPORTUL") == (11178217, "S.N. AEROPORTUL")
    assert split_buyer("A name with no number") == (None, "A name with no number")
    assert split_buyer(None) == (None, None)


def test_winner_cui_is_only_for_romanian_tax_ids():
    assert winner_cui("RO 15425816", "RO") == 15425816
    assert winner_cui("15148952", None) == 15148952
    # A valid CUI by its digits, but the company is abroad.
    assert winner_cui("15148952", "HU") is None
    assert winner_cui("23049996241", "HU") is None
    assert winner_cui("ATU14260100", "RO") is None
    # The placeholder SEAP shows where it names no winner.
    assert winner_cui("00", "RO") is None


def test_parse_notices_reads_every_kind():
    parsed = parse_notices(fixture("seap_award_notices"))

    assert parsed.rejected == []
    assert parsed.invalid_cuis == 0
    by_no = {row["notice_no"]: row for row in parsed.notices}
    assert set(by_no) == {
        "CAN1138069",
        "CAN1101786",
        "CAN1167934",
        "CAN1175575",
        "PCA1004155",
        "SCNA1137910",
    }
    notice = by_no["CAN1138069"]
    assert notice["id"] == 100660237
    assert notice["buyer_cui"] == 4364349
    assert (notice["cpv_code"], notice["contract_type_id"]) == ("45112711-2", 3)
    assert notice["procedure_type"] == "Licitatie deschisa"
    assert notice["value_ron"] == Decimal("38800893.45")
    assert notice["published_at"].isoformat() == "2026-10-08T19:00:02+03:00"
    # A framework agreement, and a notice of a cancelled procedure.
    assert by_no["CAN1167934"]["assignment_type_id"] == 3
    assert by_no["CAN1167934"]["has_subsequent_contracts"] is True
    assert by_no["CAN1175575"]["procedure_state_id"] == 3
    assert parsed.entities[2684940] == ("APA  CANAL  SIBIU SA", "authority")


def test_parse_notices_keeps_going_past_a_broken_row():
    data = fixture("seap_award_notices")
    del data["items"][0]["caNoticeId"]
    parsed = parse_notices(data)
    assert len(parsed.notices) == 5
    assert len(parsed.rejected) == 1


def test_parse_contracts_gives_one_row_per_winner():
    parsed = parse_contracts(fixture("seap_award_contracts"))

    assert parsed.rejected == []
    contracts = {row["id"]: row for row in parsed.contracts}
    assert len(contracts) == 9
    # An association of five wins one contract: one value, five winners.
    association = [row for row in parsed.winners if row["contract_id"] == 108187624]
    assert [row["position"] for row in association] == [0, 1, 2, 3, 4]
    assert {row["supplier_cui"] for row in association} == {
        15148952,
        15425816,
        15071050,
        17789473,
        28503819,
    }
    assert contracts[108187624]["value_ron"] == Decimal("38800893.45")
    assert contracts[108187624]["modified_count"] == 29
    assert contracts[108187624]["contract_date"].isoformat() == "2024-11-22T00:00:00+02:00"


def test_parse_contracts_keeps_a_foreign_winner_as_text():
    parsed = parse_contracts(fixture("seap_award_contracts"))
    foreign = next(row for row in parsed.winners if row["country"] == "Hungary")
    assert foreign["supplier_cui"] is None
    assert foreign["supplier_text"] == "23049996241 UTB Envirotec"
    placeholder = next(row for row in parsed.winners if row["contract_id"] == 108185372)
    assert (placeholder["supplier_cui"], placeholder["supplier_text"]) == (None, "00 0")
    assert parsed.invalid_cuis == 2
    assert 4491776 in parsed.entities
    assert all(kind == "company" for _, kind in parsed.entities.values())


def test_parse_contracts_tells_a_framework_from_its_contracts():
    parsed = parse_contracts(fixture("seap_award_contracts"))
    kinds = [row["kind"] for row in parsed.contracts if row["notice_id"] == 100660193]
    assert sorted(kinds) == [2, 3, 3, 3, 3, 3]
    framework = next(row for row in parsed.contracts if row["kind"] == 2)
    assert (framework["min_offer_ron"], framework["max_offer_ron"]) == (
        Decimal("273600.0"),
        Decimal("311600.0"),
    )


def test_parse_contracts_hides_a_personal_code():
    data = fixture("seap_award_contracts")
    winner = data["items"][0]["winners"][0]
    winner["fiscalNumber"], winner["name"] = "1800101221144", "POPESCU ION PFA"
    parsed = parse_contracts(data)
    first = next(
        row
        for row in parsed.winners
        if row["contract_id"] == data["items"][0]["caNoticeContractId"] and row["position"] == 0
    )
    assert first["supplier_cui"] is None
    assert first["supplier_text"] == "[CNP] POPESCU ION PFA"


def test_notice_pages_asks_one_day_and_follows_the_pages():
    items = fixture("seap_award_notices")["items"]
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        asked.append(body)
        page = items[:4] if body["pageIndex"] == 0 else items[4:]
        return httpx.Response(200, json={"total": 6, "items": page, "searchTooLong": False})

    with client(handler) as http:
        pages = list(notice_pages(http, date(2026, 10, 8)))

    assert [len(page.data["items"]) for page in pages] == [4, 2]
    assert [body["pageIndex"] for body in asked] == [0, 1]
    assert asked[0]["startPublicationDate"] == "2026-10-08T00:00:00.000Z"
    assert asked[0]["endPublicationDate"] == "2026-10-08T00:00:00.000Z"
    assert not any(page.truncated for page in pages)
    assert pages[0].url == LIST_URL
    assert json.loads(pages[1].request_body)["pageIndex"] == 1


def test_notice_pages_flags_a_day_over_the_cap():
    item = fixture("seap_award_notices")["items"][0]

    def handler(request: httpx.Request) -> httpx.Response:
        index = json.loads(request.content)["pageIndex"]
        page = [item] * 500 if index < 6 else []
        return httpx.Response(200, json={"total": 3000, "items": page, "searchTooLong": True})

    with client(handler) as http:
        pages = list(notice_pages(http, date(2026, 12, 20)))

    assert len(pages) == 6
    assert [page.truncated for page in pages] == [False] * 5 + [True]


def test_contract_pages_follows_skip_and_take():
    items = fixture("seap_award_contracts")["items"]
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        asked.append(body)
        return httpx.Response(
            200, json={"total": 9, "items": items[body["skip"] : body["skip"] + 5]}
        )

    with client(handler) as http:
        pages = list(contract_pages(http, 100660193))

    assert [body["skip"] for body in asked] == [0, 5]
    assert all(body["caNoticeId"] == 100660193 and body["sortOrder"] == [] for body in asked)
    assert sum(len(page.data["items"]) for page in pages) == 9
    assert pages[0].url == CONTRACTS_URL


def test_a_notice_without_contracts_gives_one_empty_page():
    with client(lambda request: httpx.Response(200, json={"total": 0, "items": []})) as http:
        pages = list(contract_pages(http, 100657509))
    assert len(pages) == 1
    assert pages[0].data["items"] == []


def test_an_answer_that_is_not_a_list_is_an_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["Eroare de sistem 261010-1B", "Value cannot be null."])

    with client(handler) as http, pytest.raises(SeapError):
        list(contract_pages(http, 1))
