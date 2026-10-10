from collections.abc import Iterator, Sequence
from functools import lru_cache
from itertools import batched

from sqlalchemy import Engine, create_engine, func, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

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


def upsert_rows(
    session: Session,
    model: type[DeclarativeBase],
    rows: Sequence[dict],
    index_elements: tuple[str, ...] = ("id",),
) -> None:
    """Insert rows keyed by the publisher's own id; a row already stored is replaced.

    Every column is updated except the key and `updated_at`, which is set to now, so a row
    must carry every value it means to keep.
    """
    for batch in batched(rows, 500):
        statement = insert(model).values(list(batch))
        changed = {
            column.name: statement.excluded[column.name]
            for column in model.__table__.columns
            if column.name not in (*index_elements, "updated_at")
        }
        if "updated_at" in model.__table__.columns:
            changed["updated_at"] = func.now()
        session.execute(
            statement.on_conflict_do_update(index_elements=list(index_elements), set_=changed)
        )
