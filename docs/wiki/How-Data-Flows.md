# How data flows

Data moves one way, in five steps. Each step can be redone on its own.

```
 1. Collect          2. Store raw          3. Read (parse)        4. Link              5. Serve
 ───────────         ────────────          ───────────────        ────────             ────────
 SEAP API,      ──►  S3 storage,      ──►  rows in          ──►   ties between    ──►  JSON API ──► site
 data.gov.ro         untouched,            PostgreSQL,            records, each        /v1/...       readers
 files               by SHA-256            with source            with method and                    developers
                                           and parser version     confidence
```

## 1. Collect

A **collector** is a command (`dr collect <name>`) that asks one public source for one
period. The scheduler container runs them every day from `infra/crontab`.

- It fetches **every day missed** since the first day it ever tried, because a local
  machine is often asleep. One failing day does not stop the days after it.
- Each run is recorded in `job_run` (running, succeeded, partial, failed). A day the
  source would not give in full ends as `partial`: it counts as done and is collected
  again by hand once the cause is fixed.
- It is polite: our User-Agent, one second between calls per host, retries with
  backoff.
- SEAP's list never returns more than 2,000 rows and will not page past them, so a day
  is split by the filters that work (state, contract type, dates, flags, CPV) until each
  slice fits.

## 2. Store raw

Before anything is read, the answer is written **untouched** to S3-compatible storage
under its SHA-256 fingerprint (`<source>/<sha[:2]>/<sha>`), and a `source_document` row
records the address, the request, the size and when it was fetched.

This store is private, because it can hold personal codes that the site masks. It is
what makes every figure traceable and every reading repeatable.

## 3. Read (parse)

A **parser** turns a stored document into rows. Parsers are versioned, and every stored
document can be read again with `dr reparse <name>`, with no network.

- Each reading goes through one function (`jobs.record_parse()`), which logs rejected
  rows and keeps their count and the parser version on the `source_document`. The
  sources page shows "Erori" per source.
- Tax IDs go through `parse_cui()`, which strips `RO` and spaces and checks the
  checksum.
- Personal numeric codes (CNP) of sole traders are masked as `[CNP]` before a row is
  stored.
- File formats are detected by signature, not by the label on data.gov.ro: the
  contract exports came in six layouts and five formats in six years.
- Every row keeps `source_document_id` and `parser_version`.

Institutions and companies go into one `entity` table keyed by CUI, so any name on any
page links to the same kind of page.

## 4. Link

Linking ties records from different sources together and **stores how**: a method and a
confidence level (sure, probable, possible). Today the main linking step ties Anghel
Saligny payments to SEAP contracts (`dr link pnias`). See
[Linking records](Linking-Records).

## 5. Serve

The FastAPI app serves read-only JSON under `/v1/`. Money rules (`money.py`) are applied
here, in SQL, the same way for every endpoint. Every answer about the data carries a
`source`: publisher, record, address and fetch time; for one record also the SHA-256 and
parser version; for a total, how many stored documents it is added up from.

The site calls the API from its own server and renders the pages. The only write is
`POST /v1/reports`, a reader's error report, which waits for a person to review it.

## Where the data stops

A full money trail (budget → commitment → contract → payment → subcontractor) cannot be
built from published data: payments are not published per supplier, and the systems
share no identifier. Date România shows the ends it can read and marks the middle as a
gap. See [Data sources](Data-Sources) for what is held and what is not.
