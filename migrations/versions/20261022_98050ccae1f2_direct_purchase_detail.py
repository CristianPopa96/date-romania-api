"""direct purchase detail

Revision ID: 98050ccae1f2
Revises: b348d1758a8f
Create Date: 2026-10-22 12:52:21.924813
"""

import sqlalchemy as sa
from alembic import op

revision = "98050ccae1f2"
down_revision = "b348d1758a8f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "direct_purchase_detail",
        sa.Column("purchase_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payment_condition", sa.Text(), nullable=True),
        sa.Column("delivery_condition", sa.Text(), nullable=True),
        sa.Column("eu_funded", sa.Boolean(), nullable=True),
        sa.Column("eu_fund", sa.Text(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["purchase_id"], ["direct_purchase.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("purchase_id"),
    )
    op.create_table(
        "direct_purchase_item",
        sa.Column("purchase_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cpv_code", sa.String(length=16), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("rejected", sa.Boolean(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["purchase_id"], ["direct_purchase_detail.purchase_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("purchase_id", "position"),
    )


def downgrade() -> None:
    op.drop_table("direct_purchase_item")
    op.drop_table("direct_purchase_detail")
