"""Where each programme's newest list is, and the Health programme's payment files.

Three places, one way each: the 2014-2020 lists are files of one data.gov.ro dataset; the
2021-2027 lists are attached to posts on mfe.gov.ro, found through WordPress's own search;
the Health programme keeps its lists and its monthly payments on one page of its own.
"""

import html
import json
import re
from dataclasses import dataclass
from datetime import date

import httpx

from date_romania.collectors import datagov
from date_romania.collectors.eu_projects.parse import last_day
from date_romania.collectors.http import PoliteClient
from date_romania.text import plain

DATASET = "proiecte-contractate"
POSTS = "https://mfe.gov.ro/wp-json/wp/v2/posts"
HEALTH_PAGE = (
    "https://mfe.gov.ro/minister/perioade-de-programare/perioada-2021-2027/"
    "autoritatea-de-management-pentru-programul-sanatate/monitorizare-implementare-proiecte/"
)
_UPLOAD = re.compile(
    r'href="(https://mfe\.gov\.ro/wp-content/uploads/[^"]+\.(?:xlsx|xls|zip|7z))"', re.I
)
_ANCHOR = re.compile(
    r'<a[^>]+href="(https://mfe\.gov\.ro/wp-content/uploads/[^"]+\.(?:xlsx|xls|zip|7z))"[^>]*>'
    r"(.*?)</a>",
    re.I | re.S,
)


class DiscoverError(RuntimeError):
    pass


@dataclass(frozen=True)
class Programme:
    code: str
    period: str
    name: str
    # 2014-2020: the code that starts the file titles in the data.gov.ro dataset.
    dataset_code: str | None = None
    # 2021-2027: one list per part; each part is the set of words its post must carry
    # (title and address, in `plain()` form), any one set of the alternatives.
    posts: tuple[tuple[tuple[str, ...], ...], ...] = ()
    # Posts from before this day are of an older programme with the same initials.
    posts_since: date = date(2023, 1, 1)
    health_page: bool = False


PROGRAMMES = (
    Programme("POR", "2014-2020", "Programul Operațional Regional", dataset_code="POR"),
    Programme(
        "POIM", "2014-2020", "Programul Operațional Infrastructură Mare", dataset_code="POIM"
    ),
    Programme("POC", "2014-2020", "Programul Operațional Competitivitate", dataset_code="POC"),
    Programme("POCU", "2014-2020", "Programul Operațional Capital Uman", dataset_code="POCU"),
    Programme("POAT", "2014-2020", "Programul Operațional Asistență Tehnică", dataset_code="POAT"),
    Programme(
        "POCA", "2014-2020", "Programul Operațional Capacitate Administrativă", dataset_code="POCA"
    ),
    Programme(
        "POAD",
        "2014-2020",
        "Programul Operațional Ajutorarea Persoanelor Dezavantajate",
        dataset_code="POAD",
    ),
    Programme("PEO", "2021-2027", "Programul Educație și Ocupare", posts=((("PEO",),),)),
    Programme(
        "PoIDS", "2021-2027", "Programul Incluziune și Demnitate Socială", posts=((("POIDS",),),)
    ),
    Programme(
        "PoCIDIF",
        "2021-2027",
        "Programul Creștere Inteligentă, Digitalizare și Instrumente Financiare",
        posts=((("POCIDIF",),),),
    ),
    Programme(
        "PDDTJ",
        "2021-2027",
        "Programul Dezvoltare Durabilă și Tranziție Justă",
        posts=(
            (("PDDTJ", "DEZVOLTARE", "DURABILA"),),
            (("PDDTJ", "TRANZITIE", "JUSTA"),),
        ),
    ),
    Programme(
        "PoAT",
        "2021-2027",
        "Programul Asistență Tehnică",
        posts=((("POAT",), ("ASISTENTA", "TEHNICA")),),
    ),
    Programme("PS", "2021-2027", "Programul Sănătate", health_page=True),
)
BY_CODE = {each.code: each for each in PROGRAMMES}


@dataclass(frozen=True)
class Found:
    programme: str
    # 'projects' or 'payments'
    kind: str
    # One list of a programme in several parts (PDDTJ) has a part number per list.
    part: int
    url: str
    # The publisher's title of the file or post, which names its day.
    label: str
    cut_off: date | None


def _datagov(client: PoliteClient) -> list[Found]:
    newest: dict[str, Found] = {}
    by_dataset = {each.dataset_code: each for each in PROGRAMMES if each.dataset_code}
    for resource in datagov.resources(client, DATASET):
        match = re.match(r"\s*([A-Z]+)\s*[-–]", resource.name or "")
        programme = match and by_dataset.get(match.group(1))
        day = last_day(resource.name)
        if not programme or day is None:
            continue
        found = Found(programme.code, "projects", 1, resource.url, resource.name, day)
        held = newest.get(programme.code)
        if held is None or day > held.cut_off:
            newest[programme.code] = found
    return list(newest.values())


def _posts(client: PoliteClient) -> list[dict]:
    """The posts that hold lists, newest first; WordPress says how many pages there are."""
    posts: list[dict] = []
    pages = 1
    page = 1
    while page <= min(pages, 5):
        response = client.request(
            "GET",
            POSTS,
            params={
                "search": "lista proiectelor contractate",
                "per_page": 100,
                "page": page,
                "_fields": "date,link,title",
            },
        )
        pages = int(response.headers.get("X-WP-TotalPages") or 1)
        batch = json.loads(response.content.decode("utf-8-sig"))
        if not isinstance(batch, list):
            raise DiscoverError(f"unexpected answer from {POSTS}: {response.text[:200]!r}")
        posts += batch
        page += 1
    return posts


def _from_posts(client: PoliteClient, problems: list[str]) -> list[Found]:
    posts = _posts(client)
    found: list[Found] = []
    for programme in PROGRAMMES:
        for part, alternatives in enumerate(programme.posts, 1):
            try:
                found.append(_newest_post(client, programme, part, alternatives, posts))
            except (DiscoverError, httpx.HTTPError) as exc:
                problems.append(f"{programme.code}: {exc}")
    return found


def _newest_post(client, programme: Programme, part: int, alternatives, posts) -> Found:
    """The file of the newest post that carries one of the part's sets of words."""
    matching = []
    for post in posts:
        title = html.unescape(post["title"]["rendered"])
        words = set(plain(f"{title} {post['link']}").split())
        day = date.fromisoformat(post["date"][:10])
        if day >= programme.posts_since and any(set(need) <= words for need in alternatives):
            matching.append((last_day(title) or day, day, title, post["link"]))
    if not matching:
        raise DiscoverError("no post with its list")
    cut_off, _, title, link = max(matching)
    page = client.request("GET", link)
    upload = _UPLOAD.search(page.text)
    if upload is None:
        raise DiscoverError(f"{link} links no file")
    return Found(programme.code, "projects", part, upload.group(1), title, cut_off)


def _health(client: PoliteClient) -> list[Found]:
    """The newest list, and every monthly payment file, from the Health page. A payment
    file's own link says only 'Plăți efectuate': its period is the text just before it."""
    text = client.request("GET", HEALTH_PAGE).text
    lists: list[Found] = []
    payments: list[Found] = []
    for match in _ANCHOR.finditer(text):
        url = match.group(1)
        label = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", match.group(2)))).strip()
        words = plain(label)
        if words.startswith("LISTA PROIECTELOR CONTRACTATE"):
            lists.append(Found("PS", "projects", 1, url, label, last_day(label)))
        elif words.startswith("PLATI EFECTUATE"):
            before = text[max(0, match.start() - 400) : match.start()]
            # The window can start inside a tag: drop that piece, then the whole tags.
            before = re.sub(r"<[^>]+>", " ", re.sub(r"^[^<]*>", "", before))
            period = re.sub(r"\s+", " ", html.unescape(before)).strip()[-60:]
            payments.append(Found("PS", "payments", 1, url, period, last_day(period)))
    dated = [each for each in lists if each.cut_off]
    if not dated:
        raise DiscoverError("PS: no list on the Health page")
    return [max(dated, key=lambda each: each.cut_off), *payments]


def discover(client: PoliteClient) -> tuple[list[Found], list[str]]:
    """Every file to hold: the newest list of each programme, and the Health payments;
    and what could not be found, so one place that fails does not hide the others."""
    found: list[Found] = []
    problems: list[str] = []
    for name, find in (
        ("data.gov.ro", lambda: _datagov(client)),
        ("mfe.gov.ro posts", lambda: _from_posts(client, problems)),
        ("Health page", lambda: _health(client)),
    ):
        try:
            found += find()
        except (DiscoverError, datagov.DatagovError, httpx.HTTPError, ValueError) as exc:
            problems.append(f"{name}: {exc!r}")
    return found, problems
