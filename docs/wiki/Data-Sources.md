# Data sources

## Collected today

| Key | Source | What it gives | Table(s) |
| --- | --- | --- | --- |
| `seap-direct` | [SEAP](https://e-licitatie.ro/pub/direct-acquisitions/list/1) direct purchases, by the day they were finalized | Small purchases without an auction, with buyer, supplier, CUI, value, state and contract type | `direct_purchase` |
| `seap-awards` | [SEAP](https://e-licitatie.ro/pub/notices/contract-award-notices/list/0/0) award notices, by publication day | Each notice with its contracts and winners, its detail (financing, the notice that opened the procedure) and its versions | `award_notice`, `award_contract`, `award_winner`, `award_notice_detail`, `award_notice_version` |
| `pnias-payments` | [MDLPA payment files](https://data.gov.ro/dataset/plati-programul-national-de-investitii-anghel-saligny-pnias-2026-prezent) of the Anghel Saligny programme, on data.gov.ro | One row per settlement request paid: town hall, project, builder and designer, amount | `pnias_payment` |
| `seap-exports` | SEAP's quarterly "Contracte" exports (ADR, on data.gov.ro), 2021 to today | Only the contracts of the programme's builders, and every buyer | `export_contract`, `export_buyer` |

| `siruta` | [SIRUTA](https://data.gov.ro/organization/ins), the national list of places (INS), twice a year | Every county, UAT and village with its code and the place it belongs to | `place` |
| `public-entities` | The Finance Ministry's [list of public entities](https://extranet.anaf.mfinante.gov.ro/anaf/extranet/EXECUTIEBUGETARA) ("Alte Rapoarte"), monthly | Every public entity's county, UAT and the institutions that fund it | `public_entity` |
| `local-budgets` | The Ministry of Development's [local budgets and population](https://data.gov.ro/dataset/politici-fiscale-si-bugetare-locale), on data.gov.ro | The executed budget of every UAT and county council (2024: revenue by source, spending by title and chapter), UAT population 2021 to 2024 | `local_budget`, `population` |
| `anaf` | [ANAF's web services](https://www.anaf.ro/anaf/internet/ANAF/servicii_online/servicii_web_anaf), by tax ID | County and locality of the registered office (never the street), CAEN, VAT and inactive status | `anaf_record` |

The first two are collected by day. The others come as files or lookups: a run fetches
what is not held yet and needs no date.

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
| Budget execution per institution (Forexebug) | What each institution spent, monthly, by budget chapter. The Finance Ministry's portal asks for a captcha on every search, so it cannot be collected; a bulk request to the ministry is planned | "Money in" for institutions other than town halls and county councils |
| ANAF financial statements | Turnover, staff, debts of a company, by year | Supplier pages, patterns |
| MIPE | EU funded projects and absorption | EU projects, available versus unused funds |
| TED | Notices published in the EU's Official Journal | Above-threshold procedures |
| SEAP direct purchase detail | Items bought, payment and delivery conditions | Direct purchase page |
| Voluntary payment publishers (e.g. Cluj-Napoca) | Named payments to suppliers | Payments on institution and locality pages |
| Office holders (Monitorul Oficial, gov.ro) | Who led each institution, and when | Responsibility timeline, politicians |

## Legal basis

Data is public under Law 544/2001 (access to public information), Law 98/2016 (public
procurement) and Law 179/2022 (open data and reuse). Date România republishes it under
CC BY 4.0, with the source of every record.
