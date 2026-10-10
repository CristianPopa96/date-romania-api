"""entity name search

Revision ID: de6979c2589b
Revises: 1e09fb9195fc
Create Date: 2026-10-10 12:00:52.096912
"""

import sqlalchemy as sa
from alembic import op

revision = "de6979c2589b"
down_revision = "1e09fb9195fc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # unaccent() itself is not immutable, so it cannot be used in an index; this wrapper
    # names the dictionary, which makes the result depend on its argument only.
    op.execute(
        """
        CREATE FUNCTION dr_unaccent(text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        AS $$ SELECT public.unaccent('public.unaccent', $1) $$
        """
    )
    op.create_index(
        "ix_entity_name_search",
        "entity",
        [sa.literal_column("dr_unaccent(lower(name))").label("search")],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"search": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_entity_name_search", table_name="entity")
    op.execute("DROP FUNCTION dr_unaccent(text)")
    # The extensions stay: something else may use them.
