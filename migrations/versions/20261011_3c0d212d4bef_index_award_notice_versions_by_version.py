"""index award notice versions by version

Revision ID: 3c0d212d4bef
Revises: afc759d67258
Create Date: 2026-10-11 22:44:13.152542
"""

from alembic import op

revision = "3c0d212d4bef"
down_revision = "afc759d67258"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_award_notice_version_version_id"),
        "award_notice_version",
        ["version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_award_notice_version_version_id"), table_name="award_notice_version")
