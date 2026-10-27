"""eu_project beneficiary entity

Revision ID: 79c46501a92f
Revises: 122bff0b072a
Create Date: 2026-10-27 22:49:48.864437
"""

import sqlalchemy as sa
from alembic import op

revision = "79c46501a92f"
down_revision = "122bff0b072a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eu_project", sa.Column("entity_cui", sa.BigInteger(), nullable=True))
    op.add_column("eu_project", sa.Column("entity_method", sa.String(length=32), nullable=True))
    op.add_column("eu_project", sa.Column("entity_confidence", sa.String(length=16), nullable=True))
    op.create_index(op.f("ix_eu_project_entity_cui"), "eu_project", ["entity_cui"], unique=False)
    op.create_foreign_key(
        "eu_project_entity_cui_fkey", "eu_project", "entity", ["entity_cui"], ["cui"]
    )


def downgrade() -> None:
    op.drop_constraint("eu_project_entity_cui_fkey", "eu_project", type_="foreignkey")
    op.drop_index(op.f("ix_eu_project_entity_cui"), table_name="eu_project")
    op.drop_column("eu_project", "entity_confidence")
    op.drop_column("eu_project", "entity_method")
    op.drop_column("eu_project", "entity_cui")
