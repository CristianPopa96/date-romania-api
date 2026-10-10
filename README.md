# Date România: API and collectors

The back end of Date România, a tracker of where Romanian public money goes. It
collects public data (SEAP, data.gov.ro, ANAF and others), keeps every raw file,
links the records, and serves them through a public, read-only API.

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

New migration after changing `src/date_romania/models.py`:

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
```

| Collector | Source | Table |
| --- | --- | --- |
| `seap-direct` | SEAP direct purchases, by finalization day | `direct_purchase` |

## API

Read-only, under `/v1/`, documented at http://localhost:8000/docs. Amounts are in lei
without VAT, as SEAP publishes them, and every answer names its source.

| Endpoint | What it gives |
| --- | --- |
| `/v1/stats` | How many direct purchases the database holds, their value, the days covered |
| `/v1/search?q=` | Institutions and companies by name (diacritics and small typos forgiven) or CUI |
| `/v1/institutions/{cui}` | An institution as a buyer: totals and its suppliers by value |
| `/v1/suppliers/{cui}` | A company as a supplier: totals and the institutions it sold to |
| `/v1/direct-purchases` | Purchases, filtered by `buyer`, `supplier`, `cpv`, `state`, `date_from`, `date_to` |
| `/v1/direct-purchases/{id}` | One purchase, with a link to its SEAP page |
| `/v1/rankings/suppliers`, `/v1/rankings/institutions` | The largest by value in a period |

Totals count only purchases whose offer was accepted. An accepted purchase published with
a value above 900,400 lei is left out of the totals and reported next to them as
`above_limit`, because one such value can outweigh a whole day. 900,400 lei is the legal
limit for works, the highest a direct purchase may have. Goods and services have a lower
limit, 270,120 lei, which is not applied: the list does not give the contract type.

## Layout

```
src/date_romania/
  api/          FastAPI app: `routes.py` the endpoints, `schemas.py` the answers
  collectors/   one module per public source
  models.py     SQLAlchemy models, shared by the API and the collectors
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
