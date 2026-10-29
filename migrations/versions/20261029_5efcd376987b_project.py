"""project

Revision ID: 5efcd376987b
Revises: b19bd3556f31
Create Date: 2026-10-29 21:20:15.498198
"""

import sqlalchemy as sa
from alembic import op

revision = "5efcd376987b"
down_revision = "b19bd3556f31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("key", sa.BigInteger(), nullable=False),
        sa.Column("programme", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("number", sa.String(length=64), nullable=True),
        sa.Column("beneficiary_cui", sa.BigInteger(), nullable=True),
        sa.Column("beneficiary_name", sa.Text(), nullable=True),
        sa.Column("natural_person", sa.Boolean(), nullable=False),
        sa.Column("counties", sa.ARRAY(sa.String(length=2)), nullable=False),
        sa.Column("value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("status_written", sa.Text(), nullable=True),
        sa.Column("reach", sa.String(length=16), nullable=False),
        sa.Column("gap", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(
            ["beneficiary_cui"],
            ["entity.cui"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "key", name="project_kind_key"),
    )
    op.create_index(
        op.f("ix_project_beneficiary_cui"), "project", ["beneficiary_cui"], unique=False
    )
    op.create_index(op.f("ix_project_kind"), "project", ["kind"], unique=False)
    op.create_index(op.f("ix_project_programme"), "project", ["programme"], unique=False)
    op.create_index(op.f("ix_project_reach"), "project", ["reach"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_project_reach"), table_name="project")
    op.drop_index(op.f("ix_project_programme"), table_name="project")
    op.drop_index(op.f("ix_project_kind"), table_name="project")
    op.drop_index(op.f("ix_project_beneficiary_cui"), table_name="project")
    op.drop_table("project")
