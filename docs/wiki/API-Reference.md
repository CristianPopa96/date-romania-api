# API reference

A public JSON API under `/v1/`. The interactive documentation, with every parameter and
answer shape, is at `/docs` on a running API (http://localhost:8000/docs locally), and
the OpenAPI schema at `/openapi.json`.

- **Read-only**, except `POST /v1/reports`.
- Amounts are JSON numbers, in **lei without VAT**.
- Days are Romanian days (Europe/Bucharest), written `YYYY-MM-DD`.
- Lists take `limit` (1 to 100, default 20) and `offset`.
- Every answer about the data carries a **`source`**: `publisher`, `record`, `url`,
  `fetched_at`; for one record also `sha256` and `parser_version`; for a total,
  `documents` (how many stored answers its rows were read from).
- Answers are under CC BY 4.0: reuse them naming Date România and the original source.

## System

| Endpoint | What it gives |
| --- | --- |
| `GET /v1/health` | `status` (`ok` or `degraded`), whether the database answers, the version |

## Overview and search

| Endpoint | What it gives |
| --- | --- |
| `GET /v1/stats` | How many direct purchases are held, their value, the days covered |
| `GET /v1/datasets` | Each source as held: days, records, whether the period is complete, `rejected_rows`. The place sources (SIRUTA, public entities, local budgets, ANAF) are listed once a file of theirs is held |
| `GET /v1/search?q=` | Institutions and companies by name (diacritics and small typos forgiven) or CUI; `kind=authority` or `company` |

## Institutions and companies

| Endpoint | What it gives |
| --- | --- |
| `GET /v1/institutions/{cui}` | An institution as a buyer: direct purchase totals and its suppliers by value |
| `GET /v1/suppliers/{cui}` | A company as a supplier: totals and the institutions it sold to |
| `GET /v1/institutions/{cui}/contracts` | What an institution awarded, signed in the period held |
| `GET /v1/suppliers/{cui}/contracts` | What a company won, alone and in association |

## Direct purchases

| Endpoint | What it gives |
| --- | --- |
| `GET /v1/direct-purchases` | Purchases, filtered by `buyer`, `supplier`, `cpv` (start of a code), `state` (7 is accepted), `date_from`, `date_to` |
| `GET /v1/direct-purchases/summary` | Totals for a `buyer`, a `supplier`, or the pair |
| `GET /v1/direct-purchases/{id}` | One purchase, with its SEAP page |

## Award notices and contracts

| Endpoint | What it gives |
| --- | --- |
| `GET /v1/award-notices/{id}` | One award notice, with its detail and versions |
| `GET /v1/award-notices/{id}/contracts` | Every contract in it, with winners |
| `GET /v1/award-contracts` | Contracts signed in the period held, by `buyer` or `supplier`, filtered by `cpv` and `eu_funded`; `format=csv` for a file |

## Rankings and patterns

| Endpoint | What it gives |
| --- | --- |
| `GET /v1/rankings/suppliers`, `/v1/rankings/institutions` | The largest by accepted direct purchases |
| `GET /v1/rankings/contract-suppliers`, `/v1/rankings/contract-institutions` | The largest by contract value; also `eu_funded` |
| `GET /v1/cpv-divisions` | The CPV divisions (two digits) to filter by |
| `GET /v1/patterns/near-limit` | Repeated direct purchases just under the ceiling, by buyer and supplier pair; `format=csv` for every purchase |

Every ranking takes `cpv`.

## Anghel Saligny programme

| Endpoint | What it gives |
| --- | --- |
| `GET /v1/programmes/anghel-saligny` | What was paid, by county and by file, and how many payments and projects could be tied to a SEAP contract |
| `GET /v1/programmes/anghel-saligny/projects` | Its projects, filtered by `county`, `q`, `builder`, `match` (`one`, `several`, `none`, `unnamed`) |
| `GET /v1/programmes/anghel-saligny/projects/{id}` | One project: its payments, its builders and the contracts they could be tied to, each with method and confidence |
| `GET /v1/places` | The counties: `place` (name, slugs), `uats`, `population` |
| `GET /v1/places/{county}` | A county by its slug: `figures` over its UATs and council, `council`, `uats` (population, capital spending, contracts in the period held) |
| `GET /v1/places/{county}/{uat}` | One UAT by its slugs: `figures` (`population`, `programme_payments`, `capital`, `contracts`, `supplier_counties`: local, mixed and elsewhere, `top_winners`), the town hall's `budget`, its `projects`, its `institutions`; Bucharest lists its sectors in `parts` and adds them up |
| `GET /v1/places/search?q=` | UATs by name, and villages as the UAT they belong to (`village`) |
| `GET /v1/institutions/{cui}/budget` | `place` the UAT or county a town hall or county council governs (else null); `budget` its latest executed year: `revenue_lines` (state subsidies, income tax shares, VAT shares, own revenue, EU funds, other administrations, other; they add up to `revenue`), `capital`, `chapters` largest first; `programme_payments` the Anghel Saligny payments to it, with their own dates; `funder` the institution that funds it; `located` the UAT any institution is in |

## Reports and corrections

| Endpoint | What it gives |
| --- | --- |
| `POST /v1/reports` | A reader says what is wrong on a page: `page`, `message`, `evidence` (optional). Returns 201. At most 5 reports an hour from one reader, 60 waiting in all. |
| `GET /v1/corrections` | What was corrected after accepted reports: the day, the page and what changed |

See [Reader reports](Reader-Reports) for how a report is reviewed.

## Example

```bash
curl "http://localhost:8000/v1/search?q=primaria%20cluj"
curl "http://localhost:8000/v1/award-contracts?buyer=4305857&format=csv" -o contracte.csv
```
