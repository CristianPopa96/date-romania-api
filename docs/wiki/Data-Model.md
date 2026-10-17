# Data model

One PostgreSQL 17 database is the single source of truth. The models are SQLAlchemy 2
classes in `src/date_romania/models/`, one module per source, shared by the API and the
collectors; migrations are Alembic, in `migrations/`.

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
 report
```

## Tables

| Table | One row is | Notes |
| --- | --- | --- |
| `source_document` | One stored answer or file | Source key, address, request, storage key (SHA-256), size, fetch time, parser version, rejected rows |
| `job_run` | One collector run over a period | Status `running`, `succeeded`, `partial` or `failed`; records read; error |
| `entity` | An institution or a company, by CUI | Name, kind (`authority`, `company`, `other`), county and locality (empty until ANAF), parent CUI. A search text column with `unaccent` and `pg_trgm` for typo-tolerant search. |
| `direct_purchase` | One SEAP direct purchase | Code (`DA…`), state, CPV, contract type, buyer and supplier CUI, dates, values |
| `award_notice` | One SEAP award notice, latest version held | Notice number (`CAN…`), procedure, buyer, CPV, contract type, value, publication day |
| `award_contract` | One contract in a notice | Number, signing date, kind (1 ordinary, 2 framework agreement, 3 subsequent), lots, value in lei, offers range |
| `award_winner` | One winner of a contract, in SEAP's order | More than one row means an association |
| `award_notice_detail` | The detail of a notice | Notice that opened the procedure, TED number, lots, EU funded, financing types |
| `award_notice_version` | One published version of a notice | Used to leave out the contracts of a withdrawn version |
| `pnias_payment` | One Anghel Saligny settlement request paid | County, town hall, project, ministry contract, values, amount, progress, builder and designer |
| `export_contract` | One winner of one contract in one quarterly export | Programme trace only, never in totals |
| `export_buyer` | A buyer seen in the exports | Its county, to check town hall names |
| `pnias_link` | A tie between a payment and an export contract | `method`, `confidence` |
| `report` | A reader's error report | Page, message, evidence, a keyed hash of the sender, status (`new`, `accepted`, `rejected`), the published correction |

Every data row keeps `source_document_id`, and most keep `parser_version`, so the site
can show where each figure came from.

## Raw store

Files live in S3-compatible storage (SeaweedFS locally), written by `storage.put_raw()`
under `<source>/<sha[:2]>/<sha>` and read back with `get_raw()`. The store is private.

## Changing the model

Edit the model in `models/`, then:

```bash
uv run alembic revision --autogenerate -m "what changed"
uv run dr db upgrade
```

CI runs `alembic check`, which fails if the models and the migrations disagree.
