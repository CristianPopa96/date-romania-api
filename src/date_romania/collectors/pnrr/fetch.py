"""Which editions MIPE's PNRR dashboard holds, and the files of one."""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.pnrr.parse import ENDPOINTS

BASE = "https://mfe.gov.ro/pnrr-dashboard/generator/data/"
INDEX_URL = f"{BASE}contains.json"


class PnrrError(RuntimeError):
    pass


@dataclass(frozen=True)
class Edition:
    day: date
    # endpoint -> address of its file
    files: dict[str, str]


def url_of(day: date, endpoint: str) -> str:
    return f"{BASE}{day:%Y%m%d}-{endpoint}.json.gz"


def edition_of(url: str) -> tuple[date, str] | None:
    """The day and endpoint an address names, or None for another address."""
    name = url.removeprefix(BASE)
    if name == url or not name.endswith(".json.gz"):
        return None
    stamp, _, endpoint = name.removesuffix(".json.gz").partition("-")
    try:
        return datetime.strptime(stamp, "%Y%m%d").date(), endpoint
    except ValueError:
        return None


def editions(index: dict) -> list[Edition]:
    """The editions `contains.json` lists with every file we read, newest first. Older
    editions lack some files (the measures came in September 2026)."""
    found: dict[date, dict[str, str]] = defaultdict(dict)
    for each in index.get("files") or []:
        named = edition_of(BASE + str(each.get("file") or ""))
        if named and named[1] in ENDPOINTS:
            found[named[0]][named[1]] = url_of(*named)
    return [
        Edition(day, files)
        for day, files in sorted(found.items(), reverse=True)
        if set(files) == set(ENDPOINTS)
    ]


def newest(client: PoliteClient) -> Edition:
    response = client.request("GET", INDEX_URL)
    try:
        index = json.loads(response.content.decode("utf-8-sig"))
    except ValueError as exc:
        raise PnrrError(f"unexpected answer from {INDEX_URL}: {response.text[:200]!r}") from exc
    found = editions(index if isinstance(index, dict) else {})
    if not found:
        raise PnrrError("contains.json lists no complete edition")
    return found[0]
