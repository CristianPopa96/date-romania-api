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

from date_romania import reports
from date_romania.collectors import seap_awards, seap_direct
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


@reparse_app.command("seap-direct")
def reparse_seap_direct() -> None:
    """Parse the stored SEAP direct purchase responses again, without calling SEAP."""
    _reparse(seap_direct)


@reparse_app.command("seap-awards")
def reparse_seap_awards() -> None:
    """Parse the stored SEAP award notice responses again, without calling SEAP."""
    _reparse(seap_awards)


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


def _settle(report_id: int, status: str, correction: str | None = None) -> None:
    with Session(get_engine()) as session:
        if reports.settle(session, report_id, status, correction) is None:
            typer.echo(f"no report #{report_id}", err=True)
            raise typer.Exit(1)
    typer.echo(f"#{report_id}: {status}")


@reports_app.command("accept")
def reports_accept(
    report_id: int,
    correction: Annotated[
        str, typer.Option(help="What was corrected, in Romanian. The site shows this text.")
    ],
) -> None:
    """Close a report as right, once the data is corrected. The correction becomes public."""
    _settle(report_id, reports.ACCEPTED, correction)


@reports_app.command("reject")
def reports_reject(report_id: int) -> None:
    """Close a report that was not an error. Nothing about it is shown."""
    _settle(report_id, reports.REJECTED)
