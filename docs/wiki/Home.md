# Date România: data and API

Date România is a tracker of where Romanian public money goes. This repository is its
back end: it **collects** public data, **keeps** every file exactly as received,
**reads** and **links** the records, and **serves** them through a public API that the
site (and anyone else) reads.

This wiki explains the data side: which sources are used, what happens to the data from
download to page, the rules for counting money and linking records, the API, and how to
run and operate the whole stack. The pages a reader sees are documented in the
[site wiki](https://github.com/CristianPopa96/date-romania-web/wiki).

## Start here

| If you want to… | Read |
| --- | --- |
| Understand the path data takes, in plain words | [How data flows](How-Data-Flows) |
| Know which public sources are used and what each one gives | [Data sources](Data-Sources) |
| Know why a total is what it is | [Counting money](Counting-Money) |
| Know how records are tied together, and how sure each tie is | [Linking records](Linking-Records) |
| See the tables in the database | [Data model](Data-Model) |
| Use the API | [API reference](API-Reference) |
| Run the stack on your computer | [Running the stack](Running-the-Stack) |
| Fill the database and keep it up to date | [Collecting data](Collecting-Data) |
| Review the errors readers report | [Reader reports](Reader-Reports) |
| Move it to a server | [Hosting](Hosting) |
| Change the code | [Development](Development) |

## What makes the data side strong

- **Nothing is thrown away.** Every answer from a public source is stored untouched,
  addressed by its SHA-256 fingerprint, before it is read. Any figure can be traced back
  to the exact file, and any parser can be rerun from storage without the network.
- **Every row knows where it came from.** Each record keeps the stored document it was
  read from and the parser version that read it; the API returns that with every answer.
- **Rejected rows are counted, not dropped.** Each reading of a file records how many
  rows could not be read, and the site shows it per source.
- **Money rules are written once** (`money.py`) and used by every endpoint, so totals
  cannot drift apart between pages.
- **Every link carries a method and a confidence** (sure, probable, possible).
- **Polite to the sources.** A clear User-Agent, at most one call per second per host,
  retries with backoff, and catch-up of missed days instead of bursts.
- **Portable.** Everything is configured through environment variables, files go
  through the S3 API, schedules live in the stack, and images are built by GitHub
  Actions, so it moves to any Docker host without code changes.
- **Open.** Code under AGPL-3.0, data and API answers under CC BY 4.0.

## Where things stand

As of 17.10.2026 the dataset is **frozen at 1 September to 10 October 2026** and the
scheduler is stopped on purpose. Held: 293,712 direct purchases (complete for the
period), 6,058 award notices with 77,401 contracts (4,796 of them signed in the period),
six Anghel Saligny payment files, and SEAP's contract exports from 2021 for the
programme's builders.
