"""`dr` command line: what the scheduler and developers run."""

import logging
from datetime import datetime, timedelta
from typing import Annotated

import typer
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from date_romania.collectors import seap_direct
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import DONE, missing_days, run_days
from date_romania.dates import yesterday
from date_romania.db import database_ok, get_engine
from date_romania.storage import storage_ok

log = logging.getLogger(__name__)

app = typer.Typer(no_args_is_help=True, help="Date România data tools.")
db_app = typer.Typer(no_args_is_help=True, help="Database tasks.")
collect_app = typer.Typer(no_args_is_help=True, help="Fetch a public source into the database.")
reparse_app = typer.Typer(no_args_is_help=True, help="Rebuild rows from the stored raw files.")
app.add_typer(db_app, name="db")
app.add_typer(collect_app, name="collect")
app.add_typer(reparse_app, name="reparse")

DAY = ["%Y-%m-%d"]


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


@collect_app.command("seap-direct")
def collect_seap_direct(
    date: Annotated[
        datetime | None, typer.Option(formats=DAY, help="Collect only this day.")
    ] = None,
    since: Annotated[
        datetime | None, typer.Option(formats=DAY, help="Collect from this day on.")
    ] = None,
) -> None:
    """SEAP direct purchases by finalization day. With no option, every day missed so far."""
    last = yesterday()
    with Session(get_engine()) as session, PoliteClient() as client:
        if date:
            days = [date.date()]
        elif since:
            days = [since.date() + timedelta(days=n) for n in range((last - since.date()).days + 1)]
        else:
            tried = run_days(session, seap_direct.JOB)
            days = missing_days(
                run_days(session, seap_direct.JOB, *DONE), last, first=min(tried, default=None)
            )
        # One day that keeps failing must not hold back the days after it.
        failed = []
        for day in days:
            try:
                count = seap_direct.collect_day(session, client, day)
            except Exception:
                log.exception("%s: failed", day)
                failed.append(day)
            else:
                typer.echo(f"{day}: {count} direct purchases")
    if failed:
        typer.echo(f"failed: {', '.join(str(day) for day in failed)}", err=True)
        raise typer.Exit(1)


@reparse_app.command("seap-direct")
def reparse_seap_direct() -> None:
    """Parse the stored SEAP direct purchase responses again, without calling SEAP."""
    with Session(get_engine()) as session:
        typer.echo(f"{seap_direct.reparse(session)} files parsed again")
