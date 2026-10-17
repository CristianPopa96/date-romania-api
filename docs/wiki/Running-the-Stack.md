# Running the stack

The whole platform runs on one machine with Docker Compose. The same `compose.yaml`
runs on a laptop today and on any Docker host later.

## Services

| Service | What it is | Local address |
| --- | --- | --- |
| `postgres` | PostgreSQL 17, the single source of truth | `127.0.0.1:5432` |
| `s3` | SeaweedFS, S3-compatible storage for raw files | `127.0.0.1:8333` |
| `migrate` | Applies database migrations, then exits | |
| `api` | FastAPI, the public JSON API | http://localhost:8000/docs |
| `scheduler` | Supercronic, runs the collectors from `infra/crontab` | |
| `web` | The site, from [date-romania-web](https://github.com/CristianPopa96/date-romania-web) | http://localhost:3000 |

`migrate`, `api` and `scheduler` share one image; the command picks the role. Every
port is bound to `127.0.0.1` only.

## First run

Needs Docker with Compose. Clone both repositories side by side (the `web` service
builds from `../date-romania-web`):

```bash
git clone https://github.com/CristianPopa96/date-romania-api
git clone https://github.com/CristianPopa96/date-romania-web
cd date-romania-api
cp .env.example .env      # Windows PowerShell: Copy-Item .env.example .env
```

Change the passwords in `.env`, then start what you need:

```bash
docker compose up -d --build postgres s3 api web
curl localhost:8000/v1/health          # Windows: curl.exe 127.0.0.1:8000/v1/health
```

Without `--build`, Compose pulls the images CI publishes to GitHub Container Registry
(`ghcr.io/cristianpopa96/date-romania-api` and `date-romania-web`) instead of building.

A new install has an empty database; see [Collecting data](Collecting-Data).

> **The scheduler.** `docker compose up -d` with no service names also starts
> `scheduler`, which collects every day missed so far. While the dataset is frozen it is
> left stopped: bring services up by name.

## Configuration

Everything is set through `.env` (copy `.env.example`):

| Variable | Meaning |
| --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Database account and name |
| `S3_ENDPOINT` | Leave unset for the local SeaweedFS; set it for a hosted S3 service |
| `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION` | Storage bucket and keys |
| `HTTP_USER_AGENT` | Sent with every request to a public source |
| `DATABASE_URL` | For running `dr` or the tests outside Docker (use `127.0.0.1`, not `localhost`) |
| `API_TAG`, `WEB_TAG` | Image tags to run |
| `WEB_DIR` | Where the site's checkout lives (default `../date-romania-web`) |

`.env` itself is not passed into the containers: Compose fills the `backend-env` list in
`compose.yaml` from it. A new setting goes in `config.py`, in `.env.example` and in that
list as `NAME: ${NAME:-}`, or the containers silently run with the default.

## Everyday commands

```bash
docker compose ps                        # what runs
docker compose logs -f api scheduler     # logs
docker compose up -d --build api web     # after merging a change
docker compose down                      # stop, keep the data
```

`docker compose down -v` also deletes the database and every raw file. Only use it to
start over.

## Windows notes

- Use `127.0.0.1`, not `localhost`, for the database and storage from the host: ports
  are published on IPv4 only and `localhost` tries IPv6 first and stalls.
- Use `curl.exe`, not the PowerShell `curl` alias.
- Files that run inside Linux containers (`infra/crontab`, `Dockerfile`, scripts) must
  keep LF line endings; a CRLF crontab breaks supercronic. Use
  `git config core.autocrlf input`.
