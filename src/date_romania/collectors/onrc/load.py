"""Loading one edition into `register_company`, through temporary tables, by COPY: 2.8
million companies and 4.2 million states do not fit a row-by-row insert.

One row is kept per tax ID: the registration that is not struck off, else the newest. An
edition is loaded on top of the one before, never in its place, so a company keeps the
day it was first seen, and its states the edition they changed in. Editions must be
loaded oldest first.
"""

from collections.abc import Iterable
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from date_romania.collectors.onrc.parse import DELETED, PARSER_VERSION

_COMPANY_COLUMNS = (
    "cui",
    "name",
    "name_key",
    "legal_form",
    "registration",
    "registered_on",
    "county",
    "siruta",
)

_TEMPORARY = """
create temporary table onrc_company (
    cui bigint, name text, name_key text, legal_form text, registration text,
    registered_on date, county integer, siruta integer
);
create temporary table onrc_state (registration text, code smallint);
create temporary table onrc_state_name (code smallint, name text);
"""

_MERGE = """
with state as (
    select registration, array_agg(distinct code order by code) as codes
    from onrc_state group by registration
), picked as (
    select distinct on (c.cui) c.*, coalesce(s.codes, '{}') as codes
    from onrc_company c left join state s using (registration)
    order by c.cui, :deleted = any(coalesce(s.codes, '{}')), c.registered_on desc nulls last,
        c.registration desc
)
insert into register_company (
    cui, name, name_key, legal_form, registration, registered_on, county, siruta, states,
    deleted, first_seen, last_seen, state_since, source_document_id, parser_version
)
select
    cui, name, name_key, legal_form, registration, registered_on, county, siruta,
    array(
        select coalesce(n.name, code::text) from unnest(codes) as code
        left join onrc_state_name n using (code) order by code
    ),
    :deleted = any(codes), :edition, :edition, :edition, :document, :parser
from picked
on conflict (cui) do update set
    name = excluded.name,
    name_key = excluded.name_key,
    legal_form = excluded.legal_form,
    registration = excluded.registration,
    registered_on = excluded.registered_on,
    county = excluded.county,
    siruta = excluded.siruta,
    states = excluded.states,
    deleted = excluded.deleted,
    last_seen = excluded.last_seen,
    state_since = case
        when register_company.states is distinct from excluded.states
        then excluded.state_since else register_company.state_since end,
    source_document_id = excluded.source_document_id,
    parser_version = excluded.parser_version
"""


def _copy(session: Session, table: str, columns: Iterable[str], rows: Iterable[tuple]) -> None:
    cursor = session.connection().connection.driver_connection.cursor()
    with cursor.copy(f"copy {table} ({', '.join(columns)}) from stdin") as copy:
        for row in rows:
            copy.write_row(row)


def load(
    session: Session,
    edition: date,
    document_id: int,
    companies: Iterable[tuple],
    states: Iterable[tuple[str, int]],
    state_names: dict[int, str],
) -> int:
    """Load one edition's rows on top of what is held; returns the companies it lists."""
    session.execute(text(_TEMPORARY))
    _copy(session, "onrc_company", _COMPANY_COLUMNS, companies)
    _copy(session, "onrc_state", ("registration", "code"), states)
    _copy(session, "onrc_state_name", ("code", "name"), state_names.items())
    session.execute(
        text(_MERGE),
        {
            "deleted": DELETED,
            "edition": edition,
            "document": document_id,
            "parser": PARSER_VERSION,
        },
    )
    listed = session.scalar(text("select count(distinct cui) from onrc_company"))
    session.execute(text("drop table onrc_company, onrc_state, onrc_state_name"))
    return listed
