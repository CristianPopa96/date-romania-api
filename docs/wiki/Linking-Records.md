# Linking records

Records from different sources rarely share an identifier. Date România ties them only
on stated evidence, and **every link stores its method and a confidence level**.

| Confidence | Evidence |
| --- | --- |
| **sure** | The same CUI on both records, or both named in one published record |
| **probable** | Evidence put together by us that makes the tie likely: an SMIS code in a contract title, or a builder's CUI plus a buyer with the town hall's name |
| **possible** | Weaker evidence: a name other records share, or name, amount and period only |

The site shows the level on every link, and headline figures never count a link weaker
than they say.

## The CUI joins

Institutions and companies are one `entity` table keyed by CUI. A direct purchase or a
contract names its buyer and supplier by CUI, so the institution page and the company
page are sure joins.

## Anghel Saligny: payments to SEAP contracts

The payment files of the Anghel Saligny programme are the best payment-level data
published: they name the town hall, the project and, in recent files, the builder's
CUI. The rule, in `src/date_romania/pnias_links.py`:

1. A payment names its **builder by CUI** and its **town hall by name**.
2. It is tied to the **works contracts** that builder won from a buyer whose **name is
   the town hall's**, found in SEAP's quarterly exports from 2021 on (`export_contract`).
3. The tie is **probable** when an export puts the buyer in the payment's county, or when
   no other buyer in the exports carries that name; **possible** when other buyers do. A
   buyer an export puts in another county is not tied.
4. **No tie is sure**: the payment files do not name the contract.

Ties are stored in `pnias_link`, with `method` and `confidence`, and are rebuilt
whenever either side is loaded (`dr link pnias` does it by hand).

Methods, as the API names them:

| Method | Confidence |
| --- | --- |
| `builder-cui+town-hall-name+county` | probable |
| `builder-cui+only-town-hall-of-that-name` | probable |
| `builder-cui+town-hall-name` | possible |

### Match states

Each payment, and each project, ends in one of four states:

| State | Meaning | Counted as tied? |
| --- | --- | --- |
| `one` | Exactly one contract fits | Yes |
| `several` | More than one contract fits; all are shown, none is picked | No |
| `none` | No contract found; the chain stops at the builder | No |
| `unnamed` | The file gives the builder only by name, so nothing is searched | No |

Payments from files older than 27 August 2026 name builders without CUI. Inside a
project, such a payment goes with the payments that name the same builder with its CUI.

### Why "no contract found" happens

Possible causes, not checked row by row: the contract was signed by an association of
communes or the county council; it was published before 2021; the works were bought by
direct purchase; or the town hall's name is written differently in SEAP.

## Places

`places.py` ties records to places, all through SIRUTA, the national code of every
county, UAT (the unit with a town hall) and village. `dr link places` runs it again from
what is held; every place collector and the payments collector run it after loading.

| Link | Rule | Held (18.10.2026) |
| --- | --- | --- |
| Entity -> its UAT and county (`entity.siruta`) | The UAT the Finance Ministry's list names for it; else the locality of its office at ANAF | 49,523 of 49,525 entities |
| Entity -> the institution that funds it (`entity.parent_cui`) | The first main credit holder in the Finance Ministry's list that we also hold | 8,135 institutions |
| Place -> its town hall or county council (`place.town_hall_cui`) | The entity of the list that no one funds and whose own name is the place's ("COMUNA ALBAC", "JUDETUL ALBA"); a place with two such entities gets none | 3,174 UATs, 41 counties |
| Anghel Saligny payment -> the place paid (`pnias_payment.siruta`) | The town hall's name in its county, or "Județul X prin Consiliul Județean X" | all 3,821 |

A name is matched to SIRUTA by its county, its kind (municipality, town, commune,
sector) and its name in one plain form. Old spelling is forgiven only for î written for
â between consonants and a dropped article ("Tirgu Mures", "Sfantul Gheorghe"), never a
near miss; two candidates are never told apart.

The budget of a town hall or county council is filed under the place it governs, so it
reaches the institution through `place.town_hall_cui`. No budget line is ever named on a
contract.

## Planned links

- **SMIS codes** in contract titles, to tie contracts to EU projects (probable).
- **Named payments** from voluntary publishers, to contracts (possible, by name, amount
  and period).
