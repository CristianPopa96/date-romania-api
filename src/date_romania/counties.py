"""Romania's counties: the name as written, by the name as sources type it.

Sources write a county in capitals, with or without diacritics and hyphens. Rows keep
the plain form (`collectors.sheets.plain`) so they compare; the site shows the real name.
"""

from date_romania.collectors.sheets import plain

_NAMES = (
    "Alba, Arad, Argeș, Bacău, Bihor, Bistrița-Năsăud, Botoșani, Brăila, Brașov, București, "
    "Buzău, Călărași, Caraș-Severin, Cluj, Constanța, Covasna, Dâmbovița, Dolj, Galați, "
    "Giurgiu, Gorj, Harghita, Hunedoara, Ialomița, Iași, Ilfov, Maramureș, Mehedinți, Mureș, "
    "Neamț, Olt, Prahova, Sălaj, Satu Mare, Sibiu, Suceava, Teleorman, Timiș, Tulcea, Vâlcea, "
    "Vaslui, Vrancea"
)

COUNTIES = {plain(name): name for name in _NAMES.split(", ")}


def county_name(key: str | None) -> str | None:
    """'BISTRITA NASAUD' is Bistrița-Năsăud. A name not in the list is given back as is."""
    return COUNTIES.get(key, key) if key else None
