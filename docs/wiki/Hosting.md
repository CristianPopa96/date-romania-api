# Hosting

The stack runs locally today (no domain yet) and is built to move to any Docker host
with **no code changes**. The first pick is a small server in the EU, because the data
is Romanian and some records name natural persons (GDPR).

## Why it moves easily

- Every setting is an environment variable, listed in `.env.example`.
- Raw files go only through the S3 API: SeaweedFS locally; Hetzner Object Storage,
  Cloudflare R2 or AWS S3 by changing the endpoint and keys.
- Schedules live in the stack (`infra/crontab`, run by the `scheduler` container), never
  in a host crontab or Windows Task Scheduler.
- No hosting-provider SDKs.
- Images are built by GitHub Actions and pushed to GitHub Container Registry on every
  push to `main`, for `linux/amd64` and `linux/arm64`.

## Moving

1. Copy `compose.yaml` and `.env` to the new server.
2. Restore a `pg_dump` of the database.
3. Sync the raw files with `rclone`.
4. For a hosted S3 service, uncomment `S3_ENDPOINT`, set the keys and drop the `s3`
   service.
5. `docker compose up -d` (pulls the published images).

On a host starting empty instead: run `dr collect pnias-payments`, then `dr collect
seap-exports` once; `dr collect siruta`, then `public-entities`, `local-budgets` and
`anaf`; then the daily collectors for the period wanted.

## Before going public

- The proxy in front of the site must set the reader's address itself
  (`CF-Connecting-IP`, or `X-Forwarded-For` overwritten, not appended), or the per-reader
  limit on reports can be dodged.
- The site's origin must take traffic from that proxy alone (firewall rules or
  Authenticated Origin Pulls).
- The API port stays bound to localhost, as in `compose.yaml`; only the site is exposed.
- Back up: a nightly `pg_dump` and a copy of the raw files to a second place.
- SEAP may throttle a datacenter address more readily than a home connection. Keep
  requests polite and off-peak; the data.gov.ro bulk exports are the fallback for
  history.

## Sharing before there is a domain

A free Cloudflare quick tunnel gives the local site a temporary public address without
opening ports:

```bash
cloudflared tunnel --url http://localhost:3000
```
