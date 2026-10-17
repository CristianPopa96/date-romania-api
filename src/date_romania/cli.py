"""`dr` command line: what the scheduler and developers run."""

import logging
import sys
from datetime import datetime
from types import ModuleType
from typing import Annotated

import typer
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from date_romania import places, pnias_links, reports
from date_romania.collectors import (
    anaf,
    local_budgets,
    pnias,
    public_entities,
    seap_awards,
    seap_direct,
    seap_exports,
    siruta,
)
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import collect_days, due_days
from date_romania.dates import yesterday
from date_romania.db import database_ok, get_engine
from date_romania.storage import storage_ok

app = typer.Typer(no_args_is_help=True, help="Date România data tools.")
db_app = typer.Typer(no_args_is_help=True, help="Database tasks.")
collect_app = typer.Typer(no_args_is_help=True, help="Fetch a public source into the database.")
reparse_app = typer.Typer(no_args_is_help=True, help="Rebuild rows from the stored raw files.")
app.add_typer(db_app, name="db")
app.add_typer(collect_app, name="collect")
reports_app = typer.Typer(no_args_is_help=True, help="Error reports from readers.")
link_app = typer.Typer(no_args_is_help=True, help="Tie records of different sources.")
app.add_typer(link_app, name="link")
app.add_typer(reparse_app, name="reparse")
app.add_typer(reports_app, name="reports")

DAY = ["%Y-%m-%d"]
Date = Annotated[datetime | None, typer.Option(formats=DAY, help="Collect only this day.")]
Since = Annotated[datetime | None, typer.Option(formats=DAY, help="Collect from this day on.")]


@app.callback()
def main() -> None:
    # Reports are in Romanian, and a Windows console would refuse their letters.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply all database migrations."""
    command.upgrade(Config("alembic.ini"), "head")


@app.command()
def check() -> None:
    """Check that the database and object storage are reachable."""
    db, store = database_ok(), storage_ok()
    typer.echo(f"database: {'ok' if db else 'unavailable'}")
    typer.echo(f"storage:  {'ok' if store else 'unavailable'}")
    if not (db and store):
        raise typer.Exit(1)


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Run the API."""
    uvicorn.run("date_romania.api.main:app", host=host, port=port, reload=reload)


def _collect(
    collector: ModuleType, records: str, date: datetime | None, since: datetime | None
) -> None:
    """Run a day collector for one day, a range, or every day it missed so far."""
    with Session(get_engine()) as session, PoliteClient() as client:
        days = due_days(
            session, collector.JOB, yesterday(), date and date.date(), since and since.date()
        )
        failed = collect_days(
            days,
            lambda day: collector.collect_day(session, client, day),
            lambda day, count: typer.echo(f"{day}: {count} {records}"),
        )
    if failed:
        typer.echo(f"failed: {', '.join(str(day) for day in failed)}", err=True)
        raise typer.Exit(1)


def _reparse(collector: ModuleType) -> None:
    with Session(get_engine()) as session:
        typer.echo(f"{collector.reparse(session)} files parsed again")


@collect_app.command("seap-direct")
def collect_seap_direct(date: Date = None, since: Since = None) -> None:
    """SEAP direct purchases by finalization day. With no option, every day missed so far."""
    _collect(seap_direct, "direct purchases", date, since)


@collect_app.command("seap-awards")
def collect_seap_awards(date: Date = None, since: Since = None) -> None:
    """SEAP award notices by publication day. With no option, every day missed so far."""
    _collect(seap_awards, "award notices", date, since)


@collect_app.command("seap-award-details")
def collect_seap_award_details(
    limit: Annotated[int | None, typer.Option(help="Stop after this many notices.")] = None,
) -> None:
    """The detail and versions of the award notices that lack them; safe to run again."""
    with Session(get_engine()) as session, PoliteClient() as client:
        typer.echo(f"{seap_awards.collect_details(session, client, limit)} notices")


@collect_app.command("pnias-payments")
def collect_pnias_payments() -> None:
    """Anghel Saligny payment files from data.gov.ro; only the files not held yet."""
    with Session(get_engine()) as session, PoliteClient() as client:
        typer.echo(f"{pnias.collect(session, client)} payments")


@collect_app.command("seap-exports")
def collect_seap_exports() -> None:
    """SEAP's quarterly contract exports from data.gov.ro; only the files not held yet."""
    with Session(get_engine()) as session, PoliteClient(timeout=600.0) as client:
        typer.echo(f"{seap_exports.collect(session, client)} contracts")


@collect_app.command("siruta")
def collect_siruta() -> None:
    """The newest edition of SIRUTA, the national list of places, if not held yet."""
    with Session(get_engine()) as session, PoliteClient() as client:
        typer.echo(f"{siruta.collect(session, client)} places")


@collect_app.command("public-entities")
def collect_public_entities() -> None:
    """The Finance Ministry's monthly list of public entities, if this edition is not held."""
    with Session(get_engine()) as session, PoliteClient() as client:
        typer.echo(f"{public_entities.collect(session, client)} public entities")


@collect_app.command("local-budgets")
def collect_local_budgets() -> None:
    """Town hall and county council budgets and UAT population; files not held yet."""
    with Session(get_engine()) as session, PoliteClient() as client:
        typer.echo(f"{local_budgets.collect(session, client)} rows")


@collect_app.command("anaf")
def collect_anaf(
    limit: Annotated[int | None, typer.Option(help="Ask about at most this many.")] = None,
) -> None:
    """ANAF's record of every entity not asked about yet, 100 tax IDs a second."""
    with Session(get_engine()) as session, PoliteClient() as client:
        typer.echo(f"{anaf.collect(session, client, limit)} records")


@reparse_app.command("seap-direct")
def reparse_seap_direct() -> None:
    """Parse the stored SEAP direct purchase responses again, without calling SEAP."""
    _reparse(seap_direct)


@reparse_app.command("seap-awards")
def reparse_seap_awards() -> None:
    """Parse the stored SEAP award notice responses again, without calling SEAP."""
    _reparse(seap_awards)


@reparse_app.command("pnias-payments")
def reparse_pnias_payments() -> None:
    """Parse the stored Anghel Saligny payment files again, without calling data.gov.ro."""
    _reparse(pnias)


@reparse_app.command("seap-exports")
def reparse_seap_exports() -> None:
    """Read the stored contract exports again, for the builders now in the payment files."""
    _reparse(seap_exports)


@reparse_app.command("siruta")
def reparse_siruta() -> None:
    """Load the stored SIRUTA editions again, without calling data.gov.ro."""
    _reparse(siruta)


@reparse_app.command("public-entities")
def reparse_public_entities() -> None:
    """Load the stored lists of public entities again, without calling the portal."""
    _reparse(public_entities)


@reparse_app.command("local-budgets")
def reparse_local_budgets() -> None:
    """Load the stored budget and population files again, without calling data.gov.ro."""
    _reparse(local_budgets)


@reparse_app.command("anaf")
def reparse_anaf() -> None:
    """Load the stored ANAF answers again, without calling ANAF."""
    _reparse(anaf)


@link_app.command("places")
def link_places() -> None:
    """Give every entity its county, UAT and funder, from the place sources held."""
    with Session(get_engine()) as session:
        count = places.locate(session)
        session.commit()
        typer.echo(f"{count} entities placed")


@link_app.command("pnias")
def link_pnias() -> None:
    """Tie Anghel Saligny payments to the contracts of their builders, from what is held."""
    with Session(get_engine()) as session:
        count = pnias_links.link(session)
        session.commit()
        typer.echo(f"{count} links")


@reports_app.command("list")
def reports_list(
    settled: Annotated[bool, typer.Option(help="Also the reports already reviewed.")] = False,
) -> None:
    """The reports waiting for review, oldest first."""
    with Session(get_engine()) as session:
        found = reports.queue(session, settled)
        for each in found:
            typer.echo(f"#{each.id} · {each.status} · {each.created_at:%Y-%m-%d %H:%M}")
            typer.echo(f"  page:     {each.page or '(none given)'}")
            typer.echo(f"  message:  {each.message}")
            if each.evidence:
                typer.echo(f"  evidence: {each.evidence}")
            if each.correction:
                typer.echo(f"  corrected: {each.correction}")
        typer.echo(f"{len(found)} reports")


def _settle(
    report_id: int, status: str, correction: str | None = None, page: str | None = None
) -> None:
    with Session(get_engine()) as session:
        if reports.settle(session, report_id, status, correction, page) is None:
            typer.echo(f"no report #{report_id}", err=True)
            raise typer.Exit(1)
    typer.echo(f"#{report_id}: {status}")


@reports_app.command("accept")
def reports_accept(
    report_id: int,
    correction: Annotated[
        str, typer.Option(help="What was corrected, in Romanian. The site shows this text.")
    ],
    page: Annotated[
        str | None,
        typer.Option(help="The page it is about, e.g. /contracte/123, if the reader gave none."),
    ] = None,
) -> None:
    """Close a report as right, once the data is corrected. The correction becomes public."""
    if page and not reports.site_page(page):
        typer.echo(f"not a page of the site: {page}", err=True)
        raise typer.Exit(1)
    _settle(report_id, reports.ACCEPTED, correction, page)


@reports_app.command("reject")
def reports_reject(report_id: int) -> None:
    """Close a report that was not an error. Nothing about it is shown."""
    _settle(report_id, reports.REJECTED)
