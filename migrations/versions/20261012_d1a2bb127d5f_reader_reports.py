"""reader reports

Revision ID: d1a2bb127d5f
Revises: 3c0d212d4bef
Create Date: 2026-10-12 12:18:56.802530
"""

import sqlalchemy as sa
from alembic import op

revision = "d1a2bb127d5f"
down_revision = "3c0d212d4bef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("page", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("correction", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_report_created_at"), "report", ["created_at"], unique=False)
    op.create_index(op.f("ix_report_status"), "report", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_report_status"), table_name="report")
    op.drop_index(op.f("ix_report_created_at"), table_name="report")
    op.drop_table("report")
