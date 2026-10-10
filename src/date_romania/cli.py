"""`dr` command line: what the scheduler and developers run."""

import logging
from datetime import datetime
from types import ModuleType
from typing import Annotated

import typer
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

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
app.add_typer(reparse_app, name="reparse")

DAY = ["%Y-%m-%d"]
Date = Annotated[datetime | None, typer.Option(formats=DAY, help="Collect only this day.")]
Since = Annotated[datetime | None, typer.Option(formats=DAY, help="Collect from this day on.")]


@app.callback()
def main() -> None:
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


@reparse_app.command("seap-direct")
def reparse_seap_direct() -> None:
    """Parse the stored SEAP direct purchase responses again, without calling SEAP."""
    _reparse(seap_direct)


@reparse_app.command("seap-awards")
def reparse_seap_awards() -> None:
    """Parse the stored SEAP award notice responses again, without calling SEAP."""
    _reparse(seap_awards)
