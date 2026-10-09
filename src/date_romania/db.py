from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from date_romania.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    with sessionmaker(get_engine())() as session:
        yield session


def database_ok() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("select 1"))
        return True
    except Exception:
        return False
