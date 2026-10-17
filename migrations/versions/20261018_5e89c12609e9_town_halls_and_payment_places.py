"""town halls and payment places

Revision ID: 5e89c12609e9
Revises: 3c62fb1462a1
Create Date: 2026-10-18 00:22:06.416802
"""

import sqlalchemy as sa
from alembic import op

revision = "5e89c12609e9"
down_revision = "3c62fb1462a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Filled by `dr link places`, to run once after this.
    op.add_column("place", sa.Column("town_hall_cui", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_place_town_hall_cui"), "place", ["town_hall_cui"], unique=False)
    op.add_column("pnias_payment", sa.Column("siruta", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_pnias_payment_siruta"), "pnias_payment", ["siruta"], unique=False)
    op.create_foreign_key(
        "pnias_payment_siruta_fkey", "pnias_payment", "place", ["siruta"], ["siruta"]
    )


def downgrade() -> None:
    op.drop_constraint("pnias_payment_siruta_fkey", "pnias_payment", type_="foreignkey")
    op.drop_index(op.f("ix_pnias_payment_siruta"), table_name="pnias_payment")
    op.drop_column("pnias_payment", "siruta")
    op.drop_index(op.f("ix_place_town_hall_cui"), table_name="place")
    op.drop_column("place", "town_hall_cui")
