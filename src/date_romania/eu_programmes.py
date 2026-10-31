"""The EU programmes whose lists of contracted projects are collected: their codes, names
and periods, and where each one's list is published. The collector finds the files by it;
the API names a project's programme by it, and its status by `status()`. MIPE's map of the
2021-2027 projects names each programme its own way (`map_names`); the regional
programmes and Transport are held from the map alone.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from date_romania.text import plain


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
    # 2021-2027: the map's names for the programme ('Program Regional Centru').
    map_names: tuple[str, ...] = ()

    @property
    def from_map(self) -> bool:
        """Held from MIPE's map alone, with no list of its own. Its paid figure is the
        map's validated payments, a different measure from what a list calls paid."""
        return not (self.dataset_code or self.posts or self.health_page)

    @property
    def paid_as(self) -> Literal["cumulative", "validated"]:
        return "validated" if self.from_map else "cumulative"


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
    Programme(
        "PEO",
        "2021-2027",
        "Programul Educație și Ocupare",
        posts=((("PEO",),),),
        map_names=("Program Educație și Ocupare",),
    ),
    Programme(
        "PoIDS",
        "2021-2027",
        "Programul Incluziune și Demnitate Socială",
        posts=((("POIDS",),),),
        map_names=("Program Incluziune și Demnitate Socială",),
    ),
    Programme(
        "PoCIDIF",
        "2021-2027",
        "Programul Creștere Inteligentă, Digitalizare și Instrumente Financiare",
        posts=((("POCIDIF",),),),
        map_names=("Program Creștere Inteligentă, Digitalizare și Instrumente Financiare",),
    ),
    Programme(
        "PDDTJ",
        "2021-2027",
        "Programul Dezvoltare Durabilă și Tranziție Justă",
        posts=(
            (("PDDTJ", "DEZVOLTARE", "DURABILA"),),
            (("PDDTJ", "TRANZITIE", "JUSTA"),),
        ),
        map_names=(
            "Program Dezvoltare Durabilă și Tranziție Justă (fost PDD)",
            "Program Dezvoltare Durabilă și Tranziție Justă (fost PTJ)",
        ),
    ),
    Programme(
        "PoAT",
        "2021-2027",
        "Programul Asistență Tehnică",
        posts=((("POAT",), ("ASISTENTA", "TEHNICA")),),
        map_names=("Program Asistență Tehnică",),
    ),
    Programme(
        "PS",
        "2021-2027",
        "Programul Sănătate",
        health_page=True,
        map_names=("Program Sănătate",),
    ),
    Programme("PT", "2021-2027", "Programul Transport", map_names=("Program Transport",)),
    *(
        Programme(
            code,
            "2021-2027",
            f"Programul Regional {region}",
            map_names=(f"Program Regional {region}",),
        )
        for code, region in (
            ("PRNE", "Nord-Est"),
            ("PRSE", "Sud-Est"),
            ("PRSM", "Sud Muntenia"),
            ("PRSVO", "Sud-Vest Oltenia"),
            ("PRV", "Vest"),
            ("PRNV", "Nord-Vest"),
            ("PRC", "Centru"),
            ("PRBI", "București-Ilfov"),
        )
    ),
)
BY_CODE = {each.code: each for each in PROGRAMMES}
BY_MAP_NAME = {plain(name): each for each in PROGRAMMES for name in each.map_names}


Status = Literal["in_progress", "finished", "terminated"]

# The lists' words for a project's state, in `plain` form, and ours. Any other ('etapizat',
# 'nefinalizat', 'in curs de reziliere'...) is served as written, with no status of ours.
STATUS: dict[str, Status] = {
    "IN IMPLEMENTARE": "in_progress",
    "IN DERULARE": "in_progress",
    "IN CURS DE IMPLEMENTARE": "in_progress",
    "FINALIZAT": "finished",
    "FINALIZATE": "finished",
    "PROIECT FINALIZAT": "finished",
    "REZILIAT": "terminated",
    "PROIECT REZILIAT INCETAT CU ACORDUL PARTILOR REVOCAT": "terminated",
}


def status(written: str | None) -> Status | None:
    return STATUS.get(plain(written))
