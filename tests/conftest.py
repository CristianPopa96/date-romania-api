import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from date_romania.db import database_ok, get_engine
from date_romania.models import Base


@pytest.fixture
def session():
    """A session on empty tables in a throwaway schema; skipped with no database.

    The schema is made inside a transaction that is rolled back, so tests never see or
    touch the collected data. Extensions and SQL functions still come from `public`.
    """
    if not database_ok():
        pytest.skip("needs the PostgreSQL database")
    with get_engine().connect() as connection:
        transaction = connection.begin()
        connection.execute(text("CREATE SCHEMA dr_test"))
        connection.execute(text("SET LOCAL search_path TO dr_test, public"))
        Base.metadata.create_all(connection, checkfirst=False)
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()
