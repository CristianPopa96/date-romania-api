"""eu projects

Revision ID: 122bff0b072a
Revises: fc54d9a65c72
Create Date: 2026-10-23 00:41:24.223907
"""

import sqlalchemy as sa
from alembic import op

revision = "122bff0b072a"
down_revision = "fc54d9a65c72"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eu_project_payment",
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("smis", sa.Integer(), nullable=False),
        sa.Column("programme", sa.String(length=16), nullable=False),
        sa.Column("beneficiary_name", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=True),
        sa.Column("request_kind", sa.Text(), nullable=True),
        sa.Column("request_number", sa.String(length=64), nullable=True),
        sa.Column("order_number", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("funding", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("source_document_id", "position"),
    )
    op.create_index(
        op.f("ix_eu_project_payment_paid_on"), "eu_project_payment", ["paid_on"], unique=False
    )
    op.create_index(
        op.f("ix_eu_project_payment_smis"), "eu_project_payment", ["smis"], unique=False
    )
    op.create_table(
        "eu_project",
        sa.Column("smis", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("programme", sa.String(length=16), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("beneficiary_cui", sa.BigInteger(), nullable=True),
        sa.Column("beneficiary_name", sa.Text(), nullable=True),
        sa.Column("beneficiary_type", sa.Text(), nullable=True),
        sa.Column("partners", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("cofinancing_rate", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("county", sa.Text(), nullable=True),
        sa.Column("locality", sa.Text(), nullable=True),
        sa.Column("eu_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("paid", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("cut_off", sa.Date(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["beneficiary_cui"],
            ["entity.cui"],
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("smis"),
    )
    op.create_index(
        op.f("ix_eu_project_beneficiary_cui"), "eu_project", ["beneficiary_cui"], unique=False
    )
    op.create_index(op.f("ix_eu_project_programme"), "eu_project", ["programme"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_eu_project_programme"), table_name="eu_project")
    op.drop_index(op.f("ix_eu_project_beneficiary_cui"), table_name="eu_project")
    op.drop_table("eu_project")
    op.drop_index(op.f("ix_eu_project_payment_smis"), table_name="eu_project_payment")
    op.drop_index(op.f("ix_eu_project_payment_paid_on"), table_name="eu_project_payment")
    op.drop_table("eu_project_payment")
