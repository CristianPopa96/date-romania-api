"""How a place is named and addressed on the site: 'Comuna Albac' at
`/localitati/alba/comuna-albac` (design round 8).

SIRUTA writes names in capitals with the old cedilla letters ('ORAŞ ZLATNA', 'ŢÂNŢĂRENI').
The site shows them in sentence case with the comma letters, and the kind before the
name. An address keeps the kind too, so a town and a commune of one name in one county
stay apart; the county is its full name, never its code.
"""

from date_romania import places
from date_romania.counties import county_name
from date_romania.models import Place
from date_romania.text import plain

_COMMA_LETTERS = str.maketrans("ŞşŢţ", "ȘșȚț")
# Words left in lower case inside a name: 'Baia de Arieș', 'Câmpulung la Tisa'.
_SMALL = {"de", "din", "pe", "la", "lui", "cu", "sub", "peste", "dintre", "și", "a"}

_KIND_WORD = {
    places.MUNICIPALITY: "Municipiul",
    places.TOWN: "Orașul",
    places.COMMUNE: "Comuna",
}
_KIND_SLUG = {
    places.MUNICIPALITY: "municipiul",
    places.TOWN: "oras",
    places.COMMUNE: "comuna",
}
# The words SIRUTA puts before a name, as written there.
_SIRUTA_PREFIXES = ("JUDEŢUL ", "MUNICIPIUL ", "ORAŞ ", "BUCUREŞTI ")


def _word(word: str, first: bool) -> str:
    if not first and word.lower() in _SMALL:
        return word.lower()
    return "-".join(part[:1].upper() + part[1:].lower() for part in word.split("-"))


def title(name: str) -> str:
    """'BAIA DE ARIEŞ' -> 'Baia de Arieș'; 'BISTRIŢA-NĂSĂUD' -> 'Bistrița-Năsăud'."""
    words = name.translate(_COMMA_LETTERS).split()
    return " ".join(_word(word, at == 0) for at, word in enumerate(words))


def bare(place: Place) -> str:
    """The name without the kind SIRUTA writes before it, as written there."""
    name = place.name
    for prefix in _SIRUTA_PREFIXES:
        name = name.removeprefix(prefix)
    return name


def display(place: Place) -> str:
    """The name the site shows: 'Comuna Albac', 'Orașul Zlatna', 'Municipiul București',
    'Sectorul 3', the county 'Dâmbovița', the village 'Albac'."""
    if place.kind == places.COUNTY:
        return county_name(places.county_key(place.name)) or title(bare(place))
    if place.kind == places.SECTOR:
        return title(bare(place))
    word = _KIND_WORD.get(place.kind)
    return f"{word} {title(bare(place))}" if word else title(bare(place))


def county_slug(place: Place) -> str:
    """'dambovita', 'bistrita-nasaud', 'bucuresti'."""
    return "-".join(plain(display(place)).lower().split())


def slug(place: Place) -> str:
    """'comuna-albac', 'oras-zlatna', 'municipiul-alba-iulia', 'sector-3'."""
    if place.kind == places.SECTOR:
        return "sector-" + plain(bare(place)).split()[-1]
    words = plain(bare(place)).lower().split()
    return "-".join([_KIND_SLUG.get(place.kind, ""), *words]).strip("-")
