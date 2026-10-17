# Collecting data

Collectors are `dr` commands. Inside Docker, run them in the API image:

```bash
docker compose run --rm api dr collect seap-direct --date 2026-10-06
```

Outside Docker, with [uv](https://docs.astral.sh/uv/) and the database and storage
running: `uv run dr collect seap-direct`.

## The collectors

| Command | What it fetches |
| --- | --- |
| `dr collect seap-direct` | SEAP direct purchases, by finalization day |
| `dr collect seap-awards` | SEAP award notices, by publication day, with contracts, winners, detail and versions |
| `dr collect seap-award-details` | The detail and versions of notices that a failed request left without them |
| `dr collect pnias-payments` | Anghel Saligny payment files not held yet |
| `dr collect seap-exports` | SEAP's quarterly contract exports not held yet (1.6 GB the first time, about ten minutes) |
| `dr collect siruta` | The newest SIRUTA edition (INS), if not held: every county, UAT and village |
| `dr collect public-entities` | The Finance Ministry's monthly list of public entities, if this edition is not held |
| `dr collect local-budgets` | Town hall and county council budgets and UAT population files not held yet |
| `dr collect anaf` | ANAF's record of every entity not asked yet, 100 tax IDs a call (about ten minutes the first time) |

The daily collectors take a period:

```bash
dr collect seap-direct                     # every day missed so far (first run: yesterday)
dr collect seap-direct --date 2026-10-06   # one day
dr collect seap-direct --since 2026-10-01  # from a day up to yesterday
```

A day that fails does not stop the days after it; it is tried again on the next run,
and the command exits with code 1. A day the source would not give in full ends as
`partial` and is not retried by itself: collect it again with `--date` once the cause is
fixed.

## Reading again and linking

```bash
dr reparse seap-direct         # rebuild rows from the raw store, no network
dr reparse seap-awards
dr reparse pnias-payments
dr reparse seap-exports        # after a new payment file: its new builders' contracts
dr link pnias                  # tie payments to contracts again, from what is held
dr reparse siruta              # also public-entities, local-budgets, anaf
dr link places                 # give every entity its county and UAT again
```

Reparse after deploying a parser change. After deploying api #17 on a new host, run
`dr reparse` once for all four sources, so the rejected-row counts are filled.

## Order for the programme trace

Run `pnias-payments` first, then `seap-exports`: the exports are read only for the
builders the payments name. After a new payment file, `dr reparse seap-exports` brings in
the contracts of its new builders without downloading anything.

## Order for places

Run `siruta` first: the other three sources are joined through it, and a budget or
population row whose place SIRUTA does not hold is rejected. Then `public-entities`,
`local-budgets` and `anaf`, in any order: every run places the entities again from what
is held (`dr link places`), the Finance Ministry's list first, then ANAF.

## The schedule

`infra/crontab` (UTC), run by the `scheduler` container:

| When | Command |
| --- | --- |
| Every hour | `dr check` (database and storage reachable) |
| 04:30 every day | `dr collect seap-direct` |
| 05:30 every day | `dr collect seap-awards` |
| 07:30 every day | `dr collect seap-award-details` |

The two file collectors are not scheduled yet; payment files appear about monthly and
exports quarterly.

**The dataset is frozen at 1 September to 10 October 2026** and the scheduler is
stopped. Do not start it or collect other days without the maintainer's decision.

## Checking a run

- `dr check`: are the database and storage reachable?
- `job_run` holds every run with its period, status, records and error.
- `/v1/datasets` and the site's sources page show, per source, the days read in full,
  read partly or missing, and the rows that could not be read.

## How collectors must behave

1. Store every response or file with `put_raw` and a `source_document` row before
   parsing. Parsers must be rerunnable from the raw store.
2. Record each run in `job_run` and fetch every period missed. One failing day must not
   stop later days.
3. Be polite: our User-Agent, a rate limit per host, retries with backoff.
4. Slice SEAP queries until each is under its cap.
5. Detect file formats by signature, not by label.
6. Log rejected rows, never drop them silently. Version each parser.
7. Keep `source_document_id` on every row; store method and confidence on every link.
