# Data sources

## Collected today

| Key | Source | What it gives | Table(s) |
| --- | --- | --- | --- |
| `seap-direct` | [SEAP](https://e-licitatie.ro/pub/direct-acquisitions/list/1) direct purchases, by the day they were finalized | Small purchases without an auction, with buyer, supplier, CUI, value, state and contract type | `direct_purchase` |
| `seap-awards` | [SEAP](https://e-licitatie.ro/pub/notices/contract-award-notices/list/0/0) award notices, by publication day | Each notice with its contracts and winners, its detail (financing, the notice that opened the procedure) and its versions | `award_notice`, `award_contract`, `award_winner`, `award_notice_detail`, `award_notice_version` |
| `pnias-payments` | [MDLPA payment files](https://data.gov.ro/dataset/plati-programul-national-de-investitii-anghel-saligny-pnias-2026-prezent) of the Anghel Saligny programme, on data.gov.ro | One row per settlement request paid: town hall, project, builder and designer, amount | `pnias_payment` |
| `seap-exports` | SEAP's quarterly "Contracte" exports (ADR, on data.gov.ro), 2021 to today | Only the contracts of the programme's builders, and every buyer | `export_contract`, `export_buyer` |

The first two are collected by day. The last two come as files: a run downloads the
files not held yet and needs no date.

Every source has one entry in `src/date_romania/sources.py` (key, publisher, the public
list page and the page of one record). A new source is added there first.

### Known limits

| Source | Limits |
| --- | --- |
| SEAP direct purchases | No budget line. The items bought, payment and delivery conditions are in a detail endpoint not collected yet. |
| SEAP award notices | No budget line. The number of offers is not published. Contracts appear weeks after signing: half after more than 17 days, one in ten after more than 50. |
| Anghel Saligny payments | No payment day. The town hall is named only by name, without CUI. Only the file of 27 August 2026 and later ones give the builder's CUI. |
| SEAP exports | Never enter a total, a ranking or an entity page (see [Linking records](Linking-Records)). No contract title from 2023 on. An association appears once per member, each with the whole value, and a contract is repeated in every later export. |

### The SEAP API is unofficial

SEAP's public pages are backed by an API that is not documented as public. The
collectors use it carefully: at most one call per second, retries with backoff, and
slicing so no call asks for more than the 2,000-row cap. The award notice list pages
normally and caps at 3,000, far above a day's notices.

## The frozen period

The site is being built on 40 days, **1 September to 10 October 2026** (decided
11.10.2026). No day outside it is collected, and the `scheduler` service is stopped.
The programme trace is the one exception: it reads contracts from 2021 on, because the
40 days alone tie only 2% of the payments.

## Planned, not collected yet

| Source | What it would bring | Needed for |
| --- | --- | --- |
| Budget execution (Forexebug XML) | What each institution spent, by budget chapter | Institution "money in", the gap panel |
| ANAF | County and locality of institutions and companies, VAT and inactive status, financial statements | Locality and county pages, filters, patterns |
| MIPE | EU funded projects and absorption | EU projects, available versus unused funds |
| TED | Notices published in the EU's Official Journal | Above-threshold procedures |
| SEAP direct purchase detail | Items bought, payment and delivery conditions | Direct purchase page |
| Voluntary payment publishers (e.g. Cluj-Napoca) | Named payments to suppliers | Payments on institution and locality pages |
| Office holders (Monitorul Oficial, gov.ro) | Who led each institution, and when | Responsibility timeline, politicians |

## Legal basis

Data is public under Law 544/2001 (access to public information), Law 98/2016 (public
procurement) and Law 179/2022 (open data and reuse). Date România republishes it under
CC BY 4.0, with the source of every record.
