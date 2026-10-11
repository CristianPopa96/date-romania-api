"""award notice detail and versions

Revision ID: afc759d67258
Revises: 55da399e58f0
Create Date: 2026-10-11 12:53:27.476137
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "afc759d67258"
down_revision = "55da399e58f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "award_notice_detail",
        sa.Column("notice_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("call_notice_no", sa.String(length=32), nullable=True),
        sa.Column("call_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ted_notice_no", sa.String(length=64), nullable=True),
        sa.Column("lots", sa.SmallInteger(), nullable=False),
        sa.Column("eu_funded", sa.Boolean(), nullable=True),
        sa.Column("financing_types", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("eu_funds", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("eu_project", sa.Text(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["notice_id"], ["award_notice.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("notice_id"),
    )
    op.create_table(
        "award_notice_version",
        sa.Column("notice_id", sa.BigInteger(), nullable=False),
        sa.Column("version_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state_id", sa.SmallInteger(), nullable=True),
        sa.Column("state", sa.String(length=64), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["notice_id"], ["award_notice.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("notice_id", "version_id"),
    )


def downgrade() -> None:
    op.drop_table("award_notice_version")
    op.drop_table("award_notice_detail")
