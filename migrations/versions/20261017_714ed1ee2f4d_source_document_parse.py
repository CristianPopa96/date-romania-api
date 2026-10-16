"""source document parse

Revision ID: 714ed1ee2f4d
Revises: c4b70f32010b
Create Date: 2026-10-17 00:02:23.964237
"""

import sqlalchemy as sa
from alembic import op

revision = "714ed1ee2f4d"
down_revision = "c4b70f32010b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Null for the documents held: only a parse can count what it rejects, so they get
    # their numbers from the next `dr reparse` of their source.
    op.add_column("source_document", sa.Column("parser_version", sa.SmallInteger(), nullable=True))
    op.add_column("source_document", sa.Column("rejected_rows", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("source_document", "rejected_rows")
    op.drop_column("source_document", "parser_version")
