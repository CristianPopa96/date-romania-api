# Date România: API and collectors

The back end of Date România, a tracker of where Romanian public money goes. It
collects public data (SEAP, data.gov.ro, ANAF and others), keeps every raw file,
links the records, and serves them through a public API, read-only except for a
reader's error report.

The site lives in [date-romania-web](https://github.com/CristianPopa96/date-romania-web).

## What runs

| Service | What it is | Local address |
| --- | --- | --- |
| `postgres` | PostgreSQL 17, the single source of truth | `localhost:5432` |
| `s3` | SeaweedFS, S3-compatible storage for raw files | `localhost:8333` |
| `migrate` | Applies database migrations, then exits | |
| `api` | FastAPI, public read-only JSON API | http://localhost:8000/docs |
| `scheduler` | Supercronic, runs the collectors from `infra/crontab` | |
| `web` | The site, from date-romania-web | http://localhost:3000 |

`api`, `migrate` and `scheduler` share one image; the command picks the role.

## Run the whole stack

Needs Docker with Compose. Clone both repositories side by side:

```bash
git clone https://github.com/CristianPopa96/date-romania-api
git clone https://github.com/CristianPopa96/date-romania-web
cd date-romania-api
cp .env.example .env      # then change the passwords
docker compose up -d --build
```

Check it: `curl localhost:8000/v1/health` and open http://localhost:3000.

Without `--build`, Compose pulls the images that CI publishes to GitHub Container
Registry instead of building them.

## Develop the back end

Needs [uv](https://docs.astral.sh/uv/).

```bash
uv sync
docker compose up -d postgres s3     # just the database and storage
uv run dr db upgrade                 # apply migrations
uv run dr serve --reload             # API on http://localhost:8000
uv run dr check                      # are database and storage reachable?
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

New migration after changing a model in `src/date_romania/models/`:

```bash
uv run alembic revision --autogenerate -m "what changed"
```

## Collectors

Each collector is a `dr collect` command, scheduled in `infra/crontab`. It keeps every
response untouched in the raw store before parsing it, and records each run in `job_run`.
A day that fails does not stop the days after it; it is tried again on the next run, and
the command exits with code 1. A day the source would not give in full ends as `partial`
and is not retried by itself: collect it again with `--date` once the cause is fixed.

```bash
uv run dr collect seap-direct                     # every day missed so far (first run: yesterday)
uv run dr collect seap-direct --date 2026-10-06   # one day
uv run dr collect seap-direct --since 2026-10-01  # from a day up to yesterday
uv run dr reparse seap-direct                     # rebuild the rows from the raw store
uv run dr collect seap-awards                     # the same options for every collector
uv run dr collect seap-award-details              # detail and versions of notices that lack them
uv run dr collect pnias-payments                  # Anghel Saligny payment files not held yet
uv run dr collect seap-exports                    # quarterly contract exports not held yet (1.6 GB the first time)
uv run dr reparse seap-exports                    # read the stored exports again, for the builders now named
uv run dr link pnias                              # tie payments to contracts again, from what is held
uv run dr collect siruta                          # the national list of places (INS), newest edition
uv run dr collect public-entities                 # the Finance Ministry's list of public entities
uv run dr collect local-budgets                   # town hall and county council budgets, population
uv run dr collect anaf                            # ANAF's record of every entity not asked yet
uv run dr link places                             # give every entity its county and UAT again
```

| Collector | Source | Table |
| --- | --- | --- |
| `seap-direct` | SEAP direct purchases, by finalization day | `direct_purchase` |
| `seap-awards` | SEAP award notices, by publication day, with the contracts and winners of each, its detail (financing, the notice that opened the procedure) and its versions | `award_notice`, `award_contract`, `award_winner`, `award_notice_detail`, `award_notice_version` |

| `pnias-payments` | Payment files of the Anghel Saligny programme (MDLPA, on data.gov.ro): one row per settlement request paid | `pnias_payment` |
| `seap-exports` | SEAP's quarterly "Contracte" exports (ADR, on data.gov.ro), 2021 to today: only the contracts of the programme's builders, and every buyer | `export_contract`, `export_buyer` |
| `siruta` | SIRUTA (INS, on data.gov.ro): every county, UAT and village, with the place it belongs to | `place` |
| `public-entities` | The Finance Ministry's monthly list of public entities: the UAT each works in and the institutions that fund it | `public_entity` |
| `local-budgets` | The Ministry of Development's yearly executed budget of every UAT and county council (2024), and UAT population (2021 to 2024) | `local_budget`, `population` |
| `anaf` | ANAF's register, asked by tax ID: the county and locality of the registered office (never the street), CAEN code, VAT and inactive status | `anaf_record` |

The last two come as files, not as days: a run downloads the files not held yet, and
needs no date. They serve the programme trace only:

- A payment names its builder by tax ID and its town hall by name. It is tied to the
  works contracts that builder won from a buyer whose name is that town hall's
  (`pnias_links.py`). The ties are in `pnias_link`, each with its method and confidence, and
  are built again whenever either side is loaded.
- No tie is sure: the payment files do not name the contract. It is `probable` when an
  export puts the buyer in the payment's county, or when no other buyer in the exports
  carries that name; `possible` when others do. A buyer an export puts in another
  county is not tied. `export_buyer` holds every buyer of the exports for this check.
- `export_contract` never enters a total, a ranking or an entity page. It is a second
  reading of SEAP with fewer fields; a row is one winner of a contract, and a contract is
  in every export published after it.
- Run `pnias-payments` first: the exports are read for the builders the payments name.
  After a new payment file, `dr reparse seap-exports` brings in the contracts of its new
  builders without downloading anything.
- Only the payment file of 27 August 2026 and later ones name builders by tax ID. A
  payment from an older file cannot be tied by itself; inside a project it goes with
  the payments that name the same builder with its tax ID.

The four place sources give every entity its county and UAT (`entity.siruta`, the unit
with a town hall: municipality, town, commune or Bucharest sector) and, for an
institution, the institution that funds it (`entity.parent_cui`). The Finance
Ministry's list is used first, ANAF next (`places.py`). The budgets are yearly and cover
only town halls and county councils: the ministry's per-institution reports cannot be
collected, since its portal asks for a captcha on every search. A budget row is one
column of the ministry's file, kept with the file's own column number, code and title;
the column number is what the county sheets agree on.

Four things to know before adding award notices up (`money.py` holds the rules):

- A notice is published again whenever a contract is added or changed, so the notices of
  one day carry contracts signed over several years. Count by `contract_date`, not by the
  day the notice was published.
- A framework agreement (`kind` 2) is a ceiling, not money committed. What is committed
  under it are its subsequent contracts (`kind` 3). Totals count kinds 1 and 3.
- A changed notice is published under a new id and the one before is withdrawn. When both
  are held, the contracts of the withdrawn one are left out (`award_notice_version`).
- An association wins one contract with one value; `award_winner` has a row per member and
  the value is not split between them.

## API

Under `/v1/`, documented at http://localhost:8000/docs. Amounts are in lei without VAT,
as SEAP publishes them, and every answer about the data names its source. Everything is
read-only except `POST /v1/reports`.

| Endpoint | What it gives |
| --- | --- |
| `/v1/stats` | How many direct purchases the database holds, their value, the days covered |
| `/v1/search?q=` | Institutions and companies by name (diacritics and small typos forgiven) or CUI |
| `/v1/institutions/{cui}` | An institution as a buyer: totals and its suppliers by value |
| `/v1/suppliers/{cui}` | A company as a supplier: totals and the institutions it sold to |
| `/v1/direct-purchases` | Purchases, filtered by `buyer`, `supplier`, `cpv`, `state`, `date_from`, `date_to` |
| `/v1/direct-purchases/{id}` | One purchase, with a link to its SEAP page |
| `/v1/rankings/suppliers`, `/v1/rankings/institutions` | The largest by value in a period |
| `/v1/direct-purchases/summary` | Totals of the direct purchases of a buyer, a supplier, or the pair |
| `/v1/award-notices/{id}`, `/v1/award-notices/{id}/contracts` | One award notice and every contract in it |
| `/v1/award-contracts` | Contracts signed in the period held, by buyer or winner; `format=csv` for a file |
| `/v1/institutions/{cui}/contracts`, `/v1/suppliers/{cui}/contracts` | What an institution awarded; what a company won, alone and in association |
| `/v1/rankings/contract-suppliers`, `/v1/rankings/contract-institutions` | The largest by contract value |
| `/v1/datasets` | Each source as held: days, records, whether the period is complete |
| `/v1/programmes/anghel-saligny` | The programme: what was paid, by county and by file, and how many payments and projects could be tied to a SEAP contract |
| `/v1/programmes/anghel-saligny/projects` | Its projects, filtered by `county`, `q`, `builder`, `match` |
| `/v1/programmes/anghel-saligny/projects/{id}` | One project: its payments, its builders and the contracts they could be tied to |
| `POST /v1/reports` | A reader says what is wrong on a page (`page`, `message`, `evidence`) |
| `/v1/corrections` | What was corrected after a report: the page and what changed |

A report changes nothing by itself. It waits in a queue until a person reads it:

```powershell
uv run dr reports list                            # the reports waiting, oldest first
uv run dr reports accept 12 --correction "..."    # the data is corrected; this text is published
uv run dr reports accept 12 --correction "..." --page /contracte/123   # and name the page
uv run dr reports reject 12                       # not an error; nothing is shown
```

Only an accepted report is published, and only as the correction written by the reviewer
and the page, never the reader's own text. The page is published only when it is the
address of a page the site has (`/contracte/123`, `/institutii/4981310`, `/surse`);
anything else typed there stays in the queue.

Personal numeric codes and control characters are taken out of a report before it is
stored. The queue takes at most 5 reports an hour from one reader and 60 in all. A reader
is told apart by a keyed hash of their address, which the site passes on in
`X-Forwarded-For`; the address itself is never stored, and the key lives only in the
running API, so the hash cannot be turned back.

Totals count only purchases whose offer was accepted. An accepted purchase published with
a value above 900,400 lei is left out of the totals and reported next to them as
`above_limit`, because one such value can outweigh a whole day. 900,400 lei is the legal
limit for works, the highest a direct purchase may have. Goods and services have a lower
limit, 270,120 lei, which is not applied: the list does not give the contract type.

## Layout

```
src/date_romania/
  api/          FastAPI app: `routes/` the endpoints by area, `schemas/` the answers
  collectors/   one package per public source
  money.py      what counts as money spent
  pnias_links.py  how an Anghel Saligny payment is tied to a SEAP contract
  places.py     where things are: the kinds of place, UAT names, `locate()`
  models/       SQLAlchemy models by source, shared by the API and the collectors
  storage.py    raw store: files kept untouched, addressed by SHA-256
  cui.py        Romanian tax ID parsing and checksum
  cli.py        the `dr` command
migrations/     Alembic migrations
infra/crontab   collector schedules
compose.yaml    the whole stack
```

## Moving to a host

Nothing in the code is tied to this machine. Everything is set through `.env`, raw
files go through the S3 API, and the images are published to GitHub Container
Registry. To move: copy `compose.yaml` and `.env` to the new server, restore a
`pg_dump` of the database, and sync the raw files with `rclone`. For a hosted S3
service (Hetzner Object Storage, Cloudflare R2, AWS), uncomment `S3_ENDPOINT`, set the keys
and drop the `s3` service.

## Licence

Code under [AGPL-3.0](LICENSE). Data exports and API responses under
[CC BY 4.0](DATA_LICENSE).
