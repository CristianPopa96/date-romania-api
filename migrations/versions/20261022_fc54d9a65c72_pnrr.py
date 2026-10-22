"""pnrr

Revision ID: fc54d9a65c72
Revises: 98050ccae1f2
Create Date: 2026-10-22 23:15:03.596421
"""

import sqlalchemy as sa
from alembic import op

revision = "fc54d9a65c72"
down_revision = "98050ccae1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pnrr_edition",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("allocated_eur", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("paid_eur", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("received_eur", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("prefinancing_eur", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("suspended_eur", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("revoked_eur", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("beneficiaries_contracted", sa.Integer(), nullable=True),
        sa.Column("beneficiaries_paid", sa.Integer(), nullable=True),
        sa.Column("contracts", sa.Integer(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("day"),
    )
    op.create_table(
        "pnrr_measure",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("component", sa.String(length=8), nullable=False),
        sa.Column("measure", sa.String(length=16), nullable=False),
        sa.Column("submeasure", sa.String(length=16), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("ministry", sa.String(length=32), nullable=True),
        sa.Column("ministry_name", sa.Text(), nullable=True),
        sa.Column("funding", sa.String(length=16), nullable=True),
        sa.Column("allocated_eur", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("contracted_eu_ron", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("paid_ron", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("paid_eur", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "pnrr_top_recipient",
        sa.Column("cui", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("grant", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("loan", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total_eur", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("last_received_on", sa.Date(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("cui"),
    )
    op.create_table(
        "pnrr_contract",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("number", sa.String(length=64), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("beneficiary_cui", sa.BigInteger(), nullable=True),
        sa.Column("beneficiary_name", sa.Text(), nullable=True),
        sa.Column("beneficiary_type", sa.Text(), nullable=True),
        sa.Column("natural_person", sa.Boolean(), nullable=False),
        sa.Column("ministry", sa.String(length=32), nullable=True),
        sa.Column("signed_on", sa.Date(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("impact", sa.String(length=16), nullable=True),
        sa.Column("county", sa.Text(), nullable=True),
        sa.Column("locality", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pnrr_contract_beneficiary_cui"), "pnrr_contract", ["beneficiary_cui"], unique=False
    )
    op.create_index(op.f("ix_pnrr_contract_number"), "pnrr_contract", ["number"], unique=False)
    op.create_table(
        "pnrr_contract_line",
        sa.Column("contract_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("measure_code", sa.String(length=32), nullable=False),
        sa.Column("funding", sa.String(length=16), nullable=True),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("eu", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("national", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("vat", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("ineligible", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("physical_progress", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("financial_progress", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.ForeignKeyConstraint(["contract_id"], ["pnrr_contract.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["measure_code"],
            ["pnrr_measure.code"],
        ),
        sa.PrimaryKeyConstraint("contract_id", "position"),
    )
    op.create_index(
        op.f("ix_pnrr_contract_line_measure_code"),
        "pnrr_contract_line",
        ["measure_code"],
        unique=False,
    )
    op.create_table(
        "pnrr_payment",
        sa.Column("position", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("measure_code", sa.String(length=32), nullable=False),
        sa.Column("funding", sa.String(length=16), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount_eur", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("reported_on", sa.Date(), nullable=True),
        sa.Column("beneficiary_cui", sa.BigInteger(), nullable=True),
        sa.Column("beneficiary_name", sa.Text(), nullable=True),
        sa.Column("natural_person", sa.Boolean(), nullable=False),
        sa.Column("county", sa.Text(), nullable=True),
        sa.Column("locality", sa.Text(), nullable=True),
        sa.Column("caen_division", sa.String(length=8), nullable=True),
        sa.Column("contracts_on_measure", sa.SmallInteger(), nullable=False),
        sa.Column("contract_id", sa.BigInteger(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["beneficiary_cui"],
            ["entity.cui"],
        ),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["pnrr_contract.id"],
        ),
        sa.ForeignKeyConstraint(
            ["measure_code"],
            ["pnrr_measure.code"],
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("position"),
    )
    op.create_index(
        op.f("ix_pnrr_payment_beneficiary_cui"), "pnrr_payment", ["beneficiary_cui"], unique=False
    )
    op.create_index(
        op.f("ix_pnrr_payment_contract_id"), "pnrr_payment", ["contract_id"], unique=False
    )
    op.create_index(
        op.f("ix_pnrr_payment_measure_code"), "pnrr_payment", ["measure_code"], unique=False
    )
    op.create_index(op.f("ix_pnrr_payment_paid_on"), "pnrr_payment", ["paid_on"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pnrr_payment_paid_on"), table_name="pnrr_payment")
    op.drop_index(op.f("ix_pnrr_payment_measure_code"), table_name="pnrr_payment")
    op.drop_index(op.f("ix_pnrr_payment_contract_id"), table_name="pnrr_payment")
    op.drop_index(op.f("ix_pnrr_payment_beneficiary_cui"), table_name="pnrr_payment")
    op.drop_table("pnrr_payment")
    op.drop_index(op.f("ix_pnrr_contract_line_measure_code"), table_name="pnrr_contract_line")
    op.drop_table("pnrr_contract_line")
    op.drop_index(op.f("ix_pnrr_contract_number"), table_name="pnrr_contract")
    op.drop_index(op.f("ix_pnrr_contract_beneficiary_cui"), table_name="pnrr_contract")
    op.drop_table("pnrr_contract")
    op.drop_table("pnrr_top_recipient")
    op.drop_table("pnrr_measure")
    op.drop_table("pnrr_edition")
