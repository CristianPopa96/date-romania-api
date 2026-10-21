# Date România: API and collectors

The back end of Date România, a tracker of where Romanian public money goes. It
collects public data (SEAP, data.gov.ro, ANAF and others), keeps every raw file,
links the records, and serves them through a public API, read-only except for a
reader's error report.

The site lives in [date-romania-web](https://github.com/CristianPopa96/date-romania-web).
Where the data comes from and how it is counted and linked, in plain words for anyone, is
in the [wiki](https://github.com/CristianPopa96/date-romania-api/wiki). This README is
for running and changing the code.

## How data flows

```
 1. Collect          2. Store raw          3. Read (parse)        4. Link              5. Serve
 ───────────         ────────────          ───────────────        ────────             ────────
 SEAP API,      ──►  S3 storage,      ──►  rows in          ──►   ties between    ──►  JSON API ──► site
 data.gov.ro,        untouched,            PostgreSQL,            records, each        /v1/...
 ANAF                by SHA-256            with source            with method and
                                           and parser version     confidence
```

Each step can be redone on its own: parsers rerun from the raw store with no network
(`dr reparse`), and links are rebuilt from what is held (`dr link`).

## What runs

| Service     | What it is                                            | Local address              |
| ----------- | ----------------------------------------------------- | -------------------------- |
| `postgres`  | PostgreSQL 17, the single source of truth             | `127.0.0.1:5432`           |
| `s3`        | SeaweedFS, S3-compatible storage for raw files        | `127.0.0.1:8333`           |
| `migrate`   | Applies database migrations, then exits               |                            |
| `api`       | FastAPI, public read-only JSON API                    | http://localhost:8000/docs |
| `scheduler` | Supercronic, runs the collectors from `infra/crontab` |                            |
| `web`       | The site, from date-romania-web                       | http://localhost:3000      |

`api`, `migrate` and `scheduler` share one image; the command picks the role. Every port
is bound to `127.0.0.1` only.

## Run the whole stack

Needs Docker with Compose. Clone both repositories side by side (the `web` service
builds from `../date-romania-web`):

```bash
git clone https://github.com/CristianPopa96/date-romania-api
git clone https://github.com/CristianPopa96/date-romania-web
cd date-romania-api
cp .env.example .env      # Windows PowerShell: Copy-Item .env.example .env; then change the passwords
docker compose up -d --build postgres s3 api web
```

Check it: `curl localhost:8000/v1/health` (Windows: `curl.exe 127.0.0.1:8000/v1/health`)
and open http://localhost:3000. A new install has an empty database: see
[Collectors](#collectors).

> **The scheduler.** `docker compose up -d` with no service names also starts
> `scheduler`, which collects every day missed since its last run, then a new day each
> morning. It runs the published image: after a merge, `docker compose pull scheduler`
> and `docker compose up -d scheduler`. Collecting days before 1 January 2026, or the
> detail of every direct purchase, is a long run: ask the maintainer first.

Without `--build`, Compose pulls the images that CI publishes to GitHub Container
Registry (`ghcr.io/cristianpopa96/date-romania-api` and `date-romania-web`) instead of
building them.

```bash
docker compose ps                        # what runs
docker compose logs -f api               # logs
docker compose up -d --build api web     # after merging a change
docker compose down                      # stop, keep the data
```

`docker compose down -v` also deletes the database and every raw file. Only use it to
start over.

### Configuration

Everything is set through `.env` (copy `.env.example`):

| Variable                                                   | Meaning                                                                         |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`        | Database account and name                                                       |
| `S3_ENDPOINT`                                              | Leave unset for the local SeaweedFS; set it for a hosted S3 service             |
| `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION` | Storage bucket and keys                                                         |
| `HTTP_USER_AGENT`                                          | Sent with every request to a public source                                      |
| `DATABASE_URL`                                             | For running `dr` or the tests outside Docker (use `127.0.0.1`, not `localhost`) |
| `API_TAG`, `WEB_TAG`                                       | Image tags to run                                                               |
| `WEB_DIR`                                                  | Where the site's checkout lives (default `../date-romania-web`)                 |

`.env` itself is not passed into the containers: Compose fills the `backend-env` list in
`compose.yaml` from it. A new setting goes in `config.py`, in `.env.example` and in that
list as `NAME: ${NAME:-}`, or the containers silently run with the default.

### Windows notes

- Use `127.0.0.1`, not `localhost`, for the database and storage from the host: ports
  are published on IPv4 only and `localhost` tries IPv6 first and stalls.
- Use `curl.exe`, not the PowerShell `curl` alias.
- Files that run inside Linux containers (`infra/crontab`, `Dockerfile`, scripts) must
  keep LF line endings; a CRLF crontab breaks supercronic. Use
  `git config core.autocrlf input`.

## Develop the back end

Python 3.13, managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync
docker compose up -d postgres s3     # just the database and storage
uv run dr db upgrade                 # apply migrations
uv run dr serve --reload             # API on http://localhost:8000
uv run dr check                      # are database and storage reachable?
```

CI runs exactly these; run them before calling work done:

```bash
uv run ruff check .
uv run ruff format --check .
uv run dr db upgrade
uv run alembic check                 # fails if models and migrations disagree
uv run pytest
```

New migration after changing a model in `src/date_romania/models/`:

```bash
uv run alembic revision --autogenerate -m "what changed"
uv run dr db upgrade
```

### Tests

- Database tests take the `session` fixture (`tests/conftest.py`): empty tables in a
  throwaway schema, rolled back, so they never touch collected data.
- Collectors are tested against small saved raw files in `tests/fixtures/`, never the
  live network.
- `tests/fixtures/site_stub.json` holds the answers to the calls the site makes, and
  `tests/fixtures/openapi.json` the API's schema; tests keep both equal to what the API
  answers. When an answer changes on purpose, regenerate the stub
  (`WRITE_SITE_STUB=1 uv run pytest tests/test_api_data.py`) and copy both files to
  date-romania-web (`e2e/stub/answers.json`, `openapi.json`) in the site's pull request.

## Collectors

Each collector is a `dr collect` command. It keeps every response untouched in the raw
store before parsing it, and records each run in `job_run`. A day that fails does not
stop the days after it; it is tried again on the next run, and the command exits with
code 1. A day the source would not give in full ends as `partial` and is not retried by
itself: collect it again with `--date` once the cause is fixed.

Inside Docker, run them in the API image
(`docker compose run --rm api dr collect seap-direct --date 2026-10-06`); outside, with
`uv run`.

```bash
uv run dr collect seap-direct                     # every day missed so far (first run: yesterday)
uv run dr collect seap-direct --date 2026-10-06   # one day
uv run dr collect seap-direct --since 2026-10-01  # from a day up to yesterday
uv run dr reparse seap-direct                     # rebuild the rows from the raw store
uv run dr collect seap-awards                     # the same options for every daily collector
uv run dr collect seap-award-details              # detail and versions of notices that lack them
uv run dr collect pnias-payments                  # Anghel Saligny payment files not held yet
uv run dr collect seap-exports                    # quarterly contract exports not held yet (1.6 GB, ~10 min the first time)
uv run dr reparse seap-exports                    # read the stored exports again, for the builders now named
uv run dr link pnias                              # tie payments to contracts again, from what is held
uv run dr collect siruta                          # the national list of places (INS), newest edition
uv run dr collect public-entities                 # the Finance Ministry's list of public entities
uv run dr collect local-budgets                   # town hall and county council budgets, population
uv run dr collect anaf                            # ANAF's record of every entity not asked yet (100 a call, ~10 min the first time)
uv run dr link places                             # give every entity its county and UAT again
uv run dr reparse siruta                          # also public-entities, local-budgets, anaf
```

| Collector         | Source                                                                                                                                                        | Table                                                                                           |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `seap-direct`     | SEAP direct purchases, by finalization day                                                                                                                    | `direct_purchase`                                                                               |
| `seap-awards`     | SEAP award notices, by publication day, with the contracts and winners of each, its detail (financing, the notice that opened the procedure) and its versions | `award_notice`, `award_contract`, `award_winner`, `award_notice_detail`, `award_notice_version` |
| `pnias-payments`  | Payment files of the Anghel Saligny programme (MDLPA, on data.gov.ro): one row per settlement request paid                                                    | `pnias_payment`                                                                                 |
| `seap-exports`    | SEAP's quarterly "Contracte" exports (ADR, on data.gov.ro), 2021 to today: only the contracts of the programme's builders, and every buyer                    | `export_contract`, `export_buyer`                                                               |
| `siruta`          | SIRUTA (INS, on data.gov.ro): every county, UAT and village, with the place it belongs to                                                                     | `place`                                                                                         |
| `public-entities` | The Finance Ministry's monthly list of public entities: the UAT each works in and the institutions that fund it                                               | `public_entity`                                                                                 |
| `local-budgets`   | The Ministry of Development's yearly executed budget of every UAT and county council (2024), and UAT population (2021 to 2024)                                | `local_budget`, `population`                                                                    |
| `anaf`            | ANAF's register, asked by tax ID: the county and locality of the registered office (never the street), CAEN code, VAT and inactive status                     | `anaf_record`                                                                                   |

Only `seap-direct` and `seap-awards` are collected by day. The others come as files or
lookups: a run fetches what is not held yet and needs no date. Every source has one
`PublicSource` entry in `src/date_romania/sources.py` (key, publisher, list page, page of
one record).

### Order

- **Programme trace.** Run `pnias-payments` first, then `seap-exports`: the exports are
  read only for the builders the payments name. After a new payment file,
  `dr reparse seap-exports` brings in the contracts of its new builders without
  downloading anything.
- **Places.** Run `siruta` first: the other three place sources are joined through it,
  and a budget or population row whose place SIRUTA does not hold is rejected. Then
  `public-entities`, `local-budgets` and `anaf`, in any order: every run places the
  entities again from what is held (`dr link places`).
- **On a host starting empty:** `pnias-payments`, then `seap-exports` once; `siruta`,
  then `public-entities`, `local-budgets` and `anaf`; then the daily collectors for the
  period wanted.
- Reparse after deploying a parser change. After deploying api #17 on a new host, run
  `dr reparse` once for every source, so the rejected-row counts are filled.

### The schedule

`infra/crontab` (UTC), run by the `scheduler` container:

| When                            | Command                                                                                   |
| ------------------------------- | ----------------------------------------------------------------------------------------- |
| Every hour                      | `dr check` (database and storage reachable)                                               |
| 04:30 every day                 | `dr collect seap-direct`                                                                  |
| 05:30 every day                 | `dr collect seap-awards`                                                                  |
| 07:30 every day                 | `dr collect seap-award-details`                                                           |
| 08:30 every day                 | `dr collect anaf`                                                                         |
| 09:30 on the 1st of every month | `dr collect pnias-payments`, then `dr reparse seap-exports` and `dr collect seap-exports` |

The file collectors run monthly: payment files appear about monthly, exports quarterly.
Unlike the daily jobs, a month whose run was missed (the machine asleep at that hour) is
not made up on start; it waits for the next 1st, or run the line by hand.

### Checking a run

- `dr check`: are the database and storage reachable?
- `job_run` holds every run with its period, status (`running`, `succeeded`, `partial`,
  `failed`), records and error.
- `/v1/datasets` and the site's sources page show, per source, the days read in full,
  read partly or missing, and the rows that could not be read.

### How collectors must behave

1. Store every response or file with `put_raw` and a `source_document` row before
   parsing. Parsers must be rerunnable from the raw store.
2. Go through `jobs.record_parse()` for every parse: it logs rejected rows and keeps
   their count and the parser version. Never drop rows silently. Version each parser.
3. Record each run in `job_run` and fetch every period missed. One failing day must not
   stop later days.
4. Be polite: our User-Agent, at most one call per second per host, retries with backoff.
5. SEAP's list API is unofficial and never returns more than 2,000 rows nor pages past
   them: slice a day by the filters that work (state, contract type, dates, flags, CPV)
   until each slice fits.
6. Detect file formats by signature, not by the label on data.gov.ro: the contract
   exports came in six layouts and five formats in six years.
7. Tax IDs go through `parse_cui()` (strips `RO` and spaces, checks the checksum).
   Personal numeric codes (CNP) of sole traders are masked as `[CNP]` before a row is
   stored.
8. Keep `source_document_id` on every row; store method and confidence on every link.

### Adding a collector

1. Add its `PublicSource` to `sources.py`.
2. Create a package in `collectors/`, shaped like `seap_direct/`: fetching, `parse.py`,
   `load.py`, `run.py` (`collect_day`, `reparse`).
3. Add `dr collect <name>` and `dr reparse <name>` in `cli.py` (two lines each on top of
   `_collect()` and `_reparse()`), and its line in `infra/crontab` if it runs by day.
4. Test it against small saved raw files in `tests/fixtures/`.

## Counting money

All the rules live in `src/date_romania/money.py` and are applied in SQL by every
endpoint; they are never restated in a route or a collector. Amounts are lei without
VAT, as SEAP publishes them.

- **Direct purchases.** Only accepted offers (SEAP state 7) are added up. An accepted
  purchase published above 900,400 lei (the works ceiling, the highest a direct purchase
  may have) is left out of totals and reported apart as `above_limit`. The goods and
  services ceiling (270,120 lei) is not applied to `above_limit` yet: some services
  (Annex 2 of the law) have higher ceilings and are not told apart. Each purchase stores
  its contract type since 16.10.2026.
- **Near-limit pattern** (`/v1/patterns/near-limit`): the same buyer and supplier with at
  least two accepted direct purchases, each between 90% of the ceiling of its contract
  type and the ceiling.
- **Award notices.** A notice is published again whenever a contract is added or
  changed, so count by `contract_date`, not by the publication day. Totals count
  ordinary (`kind` 1) and subsequent (`kind` 3) contracts, never framework agreements
  (`kind` 2). When a changed notice is republished under a new id, the contracts of the
  withdrawn one are left out (`award_notice_version`, `contract_in_force`). An
  association wins one contract with one value; `award_winner` has a row per member and
  the value is not split.
- Entity pages and rankings count contracts signed in the period held, with a note that
  the list is incomplete. A notice's own page shows the notice's own total.
- On a company, contracts won alone and in association are two figures, never added. In
  the supplier ranking, a contract won in association appears at every member, with its
  full value.
- Direct purchases and contracts are never added together.
- `export_contract` (the quarterly exports) never enters a total, a ranking or an entity
  page: it is a second reading of SEAP with fewer fields, a row is one winner of a
  contract, and a contract is in every export published after it.
- Figures over different periods (a 2024 budget, the days of contracts held, the dates of
  the payment files) are never added or subtracted.

## Linking records

Every link stores a `method` and a `confidence` (`sure`, `probable`, `possible`).

### Anghel Saligny payments to SEAP contracts

`src/date_romania/pnias_links.py`. A payment names its builder by tax ID and its town hall
by name. It is tied to the works contracts that builder won from a buyer whose name is
that town hall's, found in the exports from 2021 on. Ties are in `pnias_link` and are
built again whenever either side is loaded.

| Method                                    | Confidence | When                                             |
| ----------------------------------------- | ---------- | ------------------------------------------------ |
| `builder-cui+town-hall-name+county`       | probable   | An export puts the buyer in the payment's county |
| `builder-cui+only-town-hall-of-that-name` | probable   | No other buyer in the exports carries that name  |
| `builder-cui+town-hall-name`              | possible   | Other buyers carry that name                     |

No tie is sure: the payment files do not name the contract. A buyer an export puts in
another county is not tied; `export_buyer` holds every buyer of the exports for this
check. Each payment and project ends in one match state: `one` (counted as tied),
`several` (all shown, none picked), `none`, or `unnamed` (the file names the builder
without CUI, so nothing is searched). Only the file of 27 August 2026 and later ones name
builders by CUI; inside a project an older payment goes with the payments that name the
same builder with its CUI.

### Places

`places.py` ties records to places through SIRUTA; `dr link places` runs it again, and
every place collector and the payments collector run it after loading.

| Link                                                              | Rule                                                                                                                                                  |
| ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Entity -> its UAT and county (`entity.siruta`)                    | The UAT the Finance Ministry's list names for it; else the locality of its office at ANAF                                                             |
| Entity -> the institution that funds it (`entity.parent_cui`)     | The first main credit holder in the Finance Ministry's list that we also hold                                                                         |
| Place -> its town hall or county council (`place.town_hall_cui`)  | The entity of the list that no one funds and whose own name is the place's ("COMUNA ALBAC", "JUDETUL ALBA"); a place with two such entities gets none |
| Anghel Saligny payment -> the place paid (`pnias_payment.siruta`) | The town hall's name in its county, or "Județul X prin Consiliul Județean X"                                                                          |

A name is matched to SIRUTA by its county, its kind (municipality, town, commune,
sector) and its name in one plain form (`text.plain()`). Old spelling is forgiven only
for î written for â between consonants and a dropped article ("Tirgu Mures",
"Sfantul Gheorghe"), never a near miss; two candidates are never told apart.

### Local budgets

The budgets are yearly and cover only town halls and county councils: the Finance
Ministry's per-institution reports (Forexebug) cannot be collected, since its portal asks
for a captcha on every search; a bulk request to the ministry is planned. A
`local_budget` row is one column of the Ministry of Development's file, kept with the
file's own column number, code and title; the column number is what the county sheets
agree on. A county council is filed under its county. `local_money.py` turns the columns
into the lines the site shows: seven revenue lines that add up to the total (state
subsidies, income tax shares, VAT shares, own revenue, EU funds, other administrations,
other; the income tax shares sit inside own revenue in the file), capital spending and
the chapters. The budget reaches an institution through `place.town_hall_cui`; no budget
line is ever named on a contract.

## Data model

One PostgreSQL 17 database. Models are SQLAlchemy 2 classes in
`src/date_romania/models/`, one module per source, shared by the API and the collectors;
migrations are Alembic, in `migrations/`.

```
                    source_document ◄──── every row points to the document it was read from
                           ▲
 job_run                   │
                           │
 entity (cui) ◄──── buyer / supplier ──── direct_purchase
      ▲
      ├─── buyer ──── award_notice ──┬── award_contract ──── award_winner ──► entity
      │                              ├── award_notice_detail
      │                              └── award_notice_version
      │
 pnias_payment ──── pnias_link (method, confidence) ────► export_contract
                                                           export_buyer
 place (siruta) ◄── entity.siruta, pnias_payment.siruta, local_budget, population
 public_entity, anaf_record ──► entity.siruta, entity.parent_cui
 report
```

| Table                  | One row is                                                | Notes                                                                                                                                                              |
| ---------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `source_document`      | One stored answer or file                                 | Source key, address, request, storage key (SHA-256), size, fetch time, parser version, rejected rows                                                               |
| `job_run`              | One collector run over a period                           | Status, records read, error                                                                                                                                        |
| `entity`               | An institution or a company, by CUI                       | Name, kind (`authority`, `company`, `other`), county, locality, `siruta`, `parent_cui`; a search column with `unaccent` and `pg_trgm` for typo-tolerant search     |
| `direct_purchase`      | One SEAP direct purchase                                  | Code (`DA…`), state, CPV, contract type, buyer and supplier CUI, dates, values                                                                                     |
| `award_notice`         | One SEAP award notice, latest version held                | Notice number (`CAN…`), procedure, buyer, CPV, contract type, value, publication day                                                                               |
| `award_contract`       | One contract in a notice                                  | Number, signing date, kind (1 ordinary, 2 framework agreement, 3 subsequent), lots, value, offers range                                                            |
| `award_winner`         | One winner of a contract, in SEAP's order                 | More than one row means an association                                                                                                                             |
| `award_notice_detail`  | The detail of a notice                                    | Notice that opened the procedure, TED number, lots, EU funded, financing types                                                                                     |
| `award_notice_version` | One published version of a notice                         | Used to leave out the contracts of a withdrawn version                                                                                                             |
| `pnias_payment`        | One Anghel Saligny settlement request paid                | County, town hall (and its `siruta`), project, ministry contract, values, amount, progress, builder and designer                                                   |
| `export_contract`      | One winner of one contract in one quarterly export        | Programme trace only, never in totals                                                                                                                              |
| `export_buyer`         | A buyer seen in the exports                               | Its county, to check town hall names                                                                                                                               |
| `pnias_link`           | A tie between a payment and an export contract            | `method`, `confidence`                                                                                                                                             |
| `place`                | A county, UAT or village, by SIRUTA code                  | Name as INS writes it, kind (`county`, `municipality`, `town`, `commune`, `sector`, `village`), the place it belongs to, its county, urban or not, `town_hall_cui` |
| `public_entity`        | One row of the Finance Ministry's list of public entities | County and UAT as written, the UAT found in SIRUTA, up to two funders                                                                                              |
| `local_budget`         | One figure of a UAT's or county council's executed budget | The file's column number, section (`revenue`, `spending`, `chapter`), code and title as printed, amount                                                            |
| `population`           | People in a UAT at 1 January                              | Bucharest by its six sectors                                                                                                                                       |
| `anaf_record`          | ANAF's answer for one tax ID                              | Found or not, name, county and locality of the office (never the street), the UAT found in SIRUTA, CAEN, registration, VAT and inactive status                     |
| `report`               | A reader's error report                                   | Page, message, evidence, a keyed hash of the sender, status (`new`, `accepted`, `rejected`), the published correction                                              |

Every data row keeps `source_document_id`, and most keep `parser_version`. Raw files live
in S3-compatible storage, written by `storage.put_raw()` under `<source>/<sha[:2]>/<sha>`
and read back with `get_raw()`. The store is private, because it can hold personal codes
the site masks.

## API

Under `/v1/`, documented at http://localhost:8000/docs (OpenAPI schema at
`/openapi.json`).

- Read-only, except `POST /v1/reports`.
- Amounts are JSON numbers, in lei without VAT. Days are Romanian days
  (Europe/Bucharest), `YYYY-MM-DD`.
- Lists take `limit` (1 to 100, default 20) and `offset`.
- Every answer about the data carries a `source`: `publisher`, `record`, `url`,
  `fetched_at`; for one record also `sha256` and `parser_version`; for a total,
  `documents` (how many stored answers its rows were read from).
- Answers are under CC BY 4.0.

| Endpoint                                                                | What it gives                                                                                                                                                                                                                                                                                                                                                        |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/v1/health`                                                            | `status` (`ok` or `degraded`), whether the database answers, the version                                                                                                                                                                                                                                                                                             |
| `/v1/stats`                                                             | How many direct purchases the database holds, their value, the days covered                                                                                                                                                                                                                                                                                          |
| `/v1/datasets`                                                          | Each source as held: days, records, whether the period is complete, `rejected_rows`                                                                                                                                                                                                                                                                                  |
| `/v1/search?q=`                                                         | Institutions and companies by name (diacritics and small typos forgiven) or CUI; `kind=authority` or `company`                                                                                                                                                                                                                                                       |
| `/v1/institutions/{cui}`                                                | An institution as a buyer: totals and its suppliers by value                                                                                                                                                                                                                                                                                                         |
| `/v1/suppliers/{cui}`                                                   | A company as a supplier: totals and the institutions it sold to                                                                                                                                                                                                                                                                                                      |
| `/v1/direct-purchases`                                                  | Purchases, filtered by `buyer`, `supplier`, `cpv`, `state`, `date_from`, `date_to`                                                                                                                                                                                                                                                                                   |
| `/v1/direct-purchases/summary`                                          | Totals of the direct purchases of a buyer, a supplier, or the pair                                                                                                                                                                                                                                                                                                   |
| `/v1/direct-purchases/{id}`                                             | One purchase, with a link to its SEAP page                                                                                                                                                                                                                                                                                                                           |
| `/v1/award-notices/{id}`, `/v1/award-notices/{id}/contracts`            | One award notice, with its detail and versions, and every contract in it                                                                                                                                                                                                                                                                                             |
| `/v1/award-contracts`                                                   | Contracts signed in the period held, by buyer or winner, filtered by `cpv` and `eu_funded`; `format=csv` for a file                                                                                                                                                                                                                                                  |
| `/v1/institutions/{cui}/contracts`, `/v1/suppliers/{cui}/contracts`     | What an institution awarded; what a company won, alone and in association                                                                                                                                                                                                                                                                                            |
| `/v1/rankings/suppliers`, `/v1/rankings/institutions`                   | The largest by accepted direct purchases                                                                                                                                                                                                                                                                                                                             |
| `/v1/rankings/contract-suppliers`, `/v1/rankings/contract-institutions` | The largest by contract value; also `eu_funded`                                                                                                                                                                                                                                                                                                                      |
| `/v1/cpv-divisions`                                                     | The CPV divisions (two digits) every ranking can be filtered by (`cpv`)                                                                                                                                                                                                                                                                                              |
| `/v1/patterns/near-limit`                                               | Repeated direct purchases just under the ceiling, by buyer and supplier pair; `format=csv` for every purchase                                                                                                                                                                                                                                                        |
| `/v1/programmes/anghel-saligny`                                         | What was paid, by county and by file, and how many payments and projects could be tied to a SEAP contract                                                                                                                                                                                                                                                            |
| `/v1/programmes/anghel-saligny/projects`                                | Its projects, filtered by `county`, `q`, `builder`, `match`                                                                                                                                                                                                                                                                                                          |
| `/v1/programmes/anghel-saligny/projects/{id}`                           | One project: its payments, its builders and the contracts they could be tied to, each with method and confidence                                                                                                                                                                                                                                                     |
| `/v1/places`                                                            | The 42 counties, with how many UATs and people each has                                                                                                                                                                                                                                                                                                              |
| `/v1/places/{county}`                                                   | A county (`/v1/places/alba`): its figures over its UATs and council, and every UAT                                                                                                                                                                                                                                                                                   |
| `/v1/places/{county}/{uat}`                                             | One UAT (`/v1/places/alba/comuna-albac`): population, the Anghel Saligny payments to its town hall, capital spending, the contracts of every buyer located there and how much went to suppliers of the county (an association counts as local only when all its members are), who won them, its projects, institutions and localities; Bucharest adds up its sectors |
| `/v1/places/search?q=`                                                  | UATs by name, and villages, each found as the UAT it belongs to                                                                                                                                                                                                                                                                                                      |
| `/v1/institutions/{cui}/budget`                                         | For a town hall or county council: its executed budget for the latest year held (revenue lines that add up to the total, capital spending, chapters) and the Anghel Saligny payments to it, each with its own period. For any institution: the one that funds it and the UAT it is in                                                                                |
| `POST /v1/reports`                                                      | A reader says what is wrong on a page (`page`, `message`, `evidence`). Returns 201                                                                                                                                                                                                                                                                                   |
| `/v1/corrections`                                                       | What was corrected after a report: the day, the page and what changed                                                                                                                                                                                                                                                                                                |

```bash
curl "http://localhost:8000/v1/search?q=primaria%20cluj"
curl "http://localhost:8000/v1/award-contracts?buyer=4305857&format=csv" -o contracte.csv
```

## Reader reports

A report changes nothing by itself. It waits in a queue until a person reads it:

```bash
uv run dr reports list                            # the reports waiting, oldest first
uv run dr reports accept 12 --correction "..."    # the data is corrected; this text is published
uv run dr reports accept 12 --correction "..." --page /contracte/123   # and name the page
uv run dr reports reject 12                       # not an error; nothing is shown
```

In Docker: `docker compose run --rm api dr reports list`.

Only an accepted report is published, and only as the correction written by the reviewer
and the page, never the reader's own text. The page is published only when it is the
address of a page the site has (`/contracte/123`, `/institutii/4981310`, `/surse`;
`reports.site_page`, extended with every new kind of page); anything else typed there
stays in the queue.

Personal numeric codes and control characters are taken out of a report before it is
stored. The queue takes at most 5 reports an hour from one reader and 60 in all. A reader
is told apart by a keyed hash of their address, which the site passes on in
`X-Forwarded-For`; the address itself is never stored, and the key lives only in the
running API, so the hash cannot be turned back.

## Layout

```
src/date_romania/
  api/          FastAPI app: main.py, routes/ (endpoints by area), schemas/ (answers)
  collectors/   one package per public source; http.py (polite client), jobs.py (runs,
                due days, record_parse), datagov.py and sheets.py (file sources)
  money.py      what counts as money spent: every rule, written once
  local_money.py  the local budget file read once: revenue lines, capital, chapters
  pnias_links.py  how an Anghel Saligny payment is tied to a SEAP contract
  places.py     where things are: kinds of place, UAT names, and locate() for entities
  place_names.py  how a place is named and addressed: 'Comuna Albac', comuna-albac
  models/       SQLAlchemy models by source, shared by the API and the collectors
  sources.py    one PublicSource per source
  storage.py    raw store: files kept untouched, addressed by SHA-256
  reports.py    readers' error reports: queue, review, public corrections
  cui.py        Romanian tax ID parsing and checksum
  text.py       plain(): names and headers in the one form they are compared in
  personal_id.py  CNP detection and masking
  entities.py   upsert of the entity table
  dates.py      Bucharest days
  config.py     settings from environment variables only
  cli.py        the dr command (Typer)
migrations/     Alembic migrations
infra/crontab   collector schedules
compose.yaml    the whole stack
tests/          pytest, with saved raw files as fixtures
docs/wiki/      the wiki pages, published by the Wiki workflow
```

## Moving to a host

Nothing in the code is tied to this machine: every setting is an environment variable,
raw files go only through the S3 API, schedules live in the stack (`infra/crontab`),
there are no hosting-provider SDKs, and images are built by GitHub Actions for
`linux/amd64` and `linux/arm64` on every push to `main`. The first pick is a small EU
server, because the data is Romanian and some records name natural persons (GDPR).

1. Copy `compose.yaml` and `.env` to the new server.
2. Restore a `pg_dump` of the database.
3. Sync the raw files with `rclone`.
4. For a hosted S3 service (Hetzner Object Storage, Cloudflare R2, AWS), uncomment
   `S3_ENDPOINT`, set the keys and drop the `s3` service.
5. `docker compose up -d` (pulls the published images).

Before going public:

- The proxy in front of the site must set the reader's address itself
  (`CF-Connecting-IP`, or `X-Forwarded-For` overwritten, not appended), or the
  per-reader limit on reports can be dodged.
- The site's origin must take traffic from that proxy alone (firewall rules or
  Authenticated Origin Pulls).
- The API port stays bound to localhost, as in `compose.yaml`; only the site is exposed.
- Back up: a nightly `pg_dump` and a copy of the raw files to a second place.
- SEAP may throttle a datacenter address more readily than a home connection. Keep
  requests polite and off-peak; the data.gov.ro bulk exports are the fallback for
  history.

Before there is a domain, a free Cloudflare quick tunnel gives the local site a temporary
public address without opening ports: `cloudflared tunnel --url http://localhost:3000`.

## Git and pull requests

- Every push to `main` runs CI and publishes `latest` images. Work on a branch and open a
  pull request.
- Never commit `.env`, raw data files or downloaded exports.
- A change spanning both repositories is two pull requests, API first, each mentioning
  the other.
- Comments written by tools on pull requests go through the `pr-comment` workflow, so
  they appear as `github-actions[bot]`.

## The wiki

The wiki is written for readers who are not developers: where the data comes from and
how it is checked, counted and linked. Technical material belongs in this README. Its
pages live under `docs/wiki/`; the **Wiki** workflow (`.github/workflows/wiki.yml`)
copies them to the GitHub wiki on every push to `main` that changes them, and deletes
pages removed here. Edit the files in `docs/wiki/`, not the wiki itself: a direct wiki
edit is overwritten by the next publish.

## Licence

Code under [AGPL-3.0](LICENSE). Data exports and API responses under
[CC BY 4.0](DATA_LICENSE).
