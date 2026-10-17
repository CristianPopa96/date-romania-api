# Reader reports

A reader who finds an error uses the form on the site ("Raportează o eroare", in the
footer of every page and in the source panel of every record). The report goes to a
**review queue**, not a mailbox, and changes nothing by itself.

## The flow

```
 Reader fills the form ──► POST /v1/reports ──► queue (status "new")
                                                   │
                                  a person reads it (dr reports list)
                                   │                               │
                          data is wrong                     not an error
                                   │                               │
           correct the data, then dr reports accept      dr reports reject
                                   │                               │
           correction text (and page) published         nothing is shown
           in /v1/corrections and the "Corecturi" tab
```

## Reviewing

```bash
uv run dr reports list                            # the reports waiting, oldest first
uv run dr reports accept 12 --correction "..."    # the data is corrected; this text is published
uv run dr reports accept 12 --correction "..." --page /contracte/123   # and name the page
uv run dr reports reject 12                       # not an error; nothing is shown
```

In Docker: `docker compose run --rm api dr reports list`.

## What is published

- Only the **reviewer's correction text** and the page, never what the reader wrote.
- The page is published only when it is the address of a page the site has
  (`/contracte/123`, `/institutii/4981310`, `/surse`…). Anything else typed there stays
  in the queue. The list of known pages is `reports.site_page`, extended with every new
  kind of page.

## Protection

- Personal numeric codes (CNP) and control characters are removed from a report before
  it is stored. The form asks readers not to write personal data.
- A reader may send **5 reports an hour**, and the queue takes **60** in all.
- A reader is told apart by a **keyed hash** of their address, which the site passes on
  in `X-Forwarded-For`. The address itself is never stored, and the key lives only in
  the running API, so the hash cannot be turned back.
- When hosted, the proxy in front of the site must set the reader's address itself
  (`CF-Connecting-IP`, or `X-Forwarded-For` overwritten, not appended), or the limit can
  be dodged. See [Hosting](Hosting).

## Not yet

A request to remove personal data has its own procedure, planned for a later release:
it needs a way to answer the person and a written process. Until then, the form takes
errors only.
