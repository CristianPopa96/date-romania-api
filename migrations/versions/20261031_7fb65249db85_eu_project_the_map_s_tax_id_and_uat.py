"""eu project: the lead's tax ID and the UAT, as MIPE's map of the 2021-2027 projects gives them

Revision ID: 7fb65249db85
Revises: 153c453895ad
Create Date: 2026-10-31 02:44:01.029235
"""

import sqlalchemy as sa
from alembic import op

revision = "7fb65249db85"
down_revision = "153c453895ad"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eu_project", sa.Column("map_cui", sa.BigInteger(), nullable=True))
    op.add_column("eu_project", sa.Column("siruta", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_eu_project_map_cui"), "eu_project", ["map_cui"], unique=False)
    op.create_index(op.f("ix_eu_project_siruta"), "eu_project", ["siruta"], unique=False)
    op.create_foreign_key("eu_project_map_cui_fkey", "eu_project", "entity", ["map_cui"], ["cui"])


def downgrade() -> None:
    op.drop_constraint("eu_project_map_cui_fkey", "eu_project", type_="foreignkey")
    op.drop_index(op.f("ix_eu_project_siruta"), table_name="eu_project")
    op.drop_index(op.f("ix_eu_project_map_cui"), table_name="eu_project")
    op.drop_column("eu_project", "siruta")
    op.drop_column("eu_project", "map_cui")
