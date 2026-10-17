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

## Planned links

- **SMIS codes** in contract titles, to tie contracts to EU projects (probable).
- **Named payments** from voluntary publishers, to contracts (possible, by name, amount
  and period).
- **Budget execution** to contracts, through the buyer's CUI (sure at the institution
  level; no budget line is ever named on a contract).
