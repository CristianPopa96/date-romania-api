"""The EU programmes whose lists of contracted projects are collected: their codes, names
and periods, and where each one's list is published. The collector finds the files by it;
the API names a project's programme by it.
"""

from dataclasses import dataclass
from datetime import date


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
