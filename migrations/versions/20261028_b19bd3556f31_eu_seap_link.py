"""eu seap link

Revision ID: b19bd3556f31
Revises: 79c46501a92f
Create Date: 2026-10-28 11:46:10.220684
"""

import sqlalchemy as sa
from alembic import op

revision = "b19bd3556f31"
down_revision = "79c46501a92f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eu_seap_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("smis", sa.Integer(), nullable=True),
        sa.Column("pnrr_contract_id", sa.BigInteger(), nullable=True),
        sa.Column("notice_id", sa.BigInteger(), nullable=True),
        sa.Column("purchase_id", sa.BigInteger(), nullable=True),
        sa.Column("cited", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.CheckConstraint("num_nonnulls(notice_id, purchase_id) = 1", name="eu_seap_link_record"),
        sa.CheckConstraint("num_nonnulls(smis, pnrr_contract_id) = 1", name="eu_seap_link_project"),
        sa.ForeignKeyConstraint(["notice_id"], ["award_notice.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pnrr_contract_id"], ["pnrr_contract.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["purchase_id"], ["direct_purchase.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["smis"], ["eu_project.smis"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_eu_seap_link_notice_id"), "eu_seap_link", ["notice_id"], unique=False)
    op.create_index(
        op.f("ix_eu_seap_link_pnrr_contract_id"), "eu_seap_link", ["pnrr_contract_id"], unique=False
    )
    op.create_index(
        op.f("ix_eu_seap_link_purchase_id"), "eu_seap_link", ["purchase_id"], unique=False
    )
    op.create_index(op.f("ix_eu_seap_link_smis"), "eu_seap_link", ["smis"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_eu_seap_link_smis"), table_name="eu_seap_link")
    op.drop_index(op.f("ix_eu_seap_link_purchase_id"), table_name="eu_seap_link")
    op.drop_index(op.f("ix_eu_seap_link_pnrr_contract_id"), table_name="eu_seap_link")
    op.drop_index(op.f("ix_eu_seap_link_notice_id"), table_name="eu_seap_link")
    op.drop_table("eu_seap_link")
