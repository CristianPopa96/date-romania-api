"""places and local budgets

Revision ID: 3c62fb1462a1
Revises: 714ed1ee2f4d
Create Date: 2026-10-17 23:38:34.183860
"""

import sqlalchemy as sa
from alembic import op

revision = "3c62fb1462a1"
down_revision = "714ed1ee2f4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Empty until `dr collect siruta`, then `public-entities`, `local-budgets` and `anaf`
    # fill them; each run places the entities again (`dr link places`).
    op.create_table(
        "place",
        sa.Column("siruta", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("parent", sa.Integer(), nullable=True),
        sa.Column("county", sa.Integer(), nullable=True),
        sa.Column("urban", sa.Boolean(), nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["county"],
            ["place.siruta"],
        ),
        sa.ForeignKeyConstraint(
            ["parent"],
            ["place.siruta"],
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("siruta"),
    )
    op.create_index(op.f("ix_place_county"), "place", ["county"], unique=False)
    op.create_index(op.f("ix_place_kind"), "place", ["kind"], unique=False)
    op.create_index(op.f("ix_place_parent"), "place", ["parent"], unique=False)
    op.create_table(
        "anaf_record",
        sa.Column("cui", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("asked_on", sa.Date(), nullable=False),
        sa.Column("found", sa.Boolean(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("county", sa.String(length=64), nullable=True),
        sa.Column("county_code", sa.String(length=2), nullable=True),
        sa.Column("locality", sa.Text(), nullable=True),
        sa.Column("siruta", sa.Integer(), nullable=True),
        sa.Column("caen", sa.Integer(), nullable=True),
        sa.Column("registration", sa.Text(), nullable=True),
        sa.Column("inactive", sa.Boolean(), nullable=True),
        sa.Column("vat_payer", sa.Boolean(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["siruta"],
            ["place.siruta"],
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("cui"),
    )
    op.create_index(op.f("ix_anaf_record_siruta"), "anaf_record", ["siruta"], unique=False)
    op.create_table(
        "local_budget",
        sa.Column("siruta", sa.Integer(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("column_no", sa.SmallInteger(), nullable=False),
        sa.Column("section", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["siruta"],
            ["place.siruta"],
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("siruta", "year", "column_no"),
    )
    op.create_table(
        "population",
        sa.Column("siruta", sa.Integer(), nullable=False),
        sa.Column("on", sa.Date(), nullable=False),
        sa.Column("people", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["siruta"],
            ["place.siruta"],
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("siruta", "on"),
    )
    op.create_table(
        "public_entity",
        sa.Column("cui", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("county", sa.String(length=64), nullable=False),
        sa.Column("uat", sa.Text(), nullable=False),
        sa.Column("siruta", sa.Integer(), nullable=True),
        sa.Column("funder_cui", sa.BigInteger(), nullable=True),
        sa.Column("funder_name", sa.Text(), nullable=True),
        sa.Column("second_funder_cui", sa.BigInteger(), nullable=True),
        sa.Column("second_funder_name", sa.Text(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.SmallInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["siruta"],
            ["place.siruta"],
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
        ),
        sa.PrimaryKeyConstraint("cui"),
    )
    op.create_index(op.f("ix_public_entity_siruta"), "public_entity", ["siruta"], unique=False)
    op.add_column("entity", sa.Column("siruta", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_entity_siruta"), "entity", ["siruta"], unique=False)
    op.create_foreign_key("entity_siruta_fkey", "entity", "place", ["siruta"], ["siruta"])


def downgrade() -> None:
    op.drop_constraint("entity_siruta_fkey", "entity", type_="foreignkey")
    op.drop_index(op.f("ix_entity_siruta"), table_name="entity")
    op.drop_column("entity", "siruta")
    op.drop_index(op.f("ix_public_entity_siruta"), table_name="public_entity")
    op.drop_table("public_entity")
    op.drop_table("population")
    op.drop_table("local_budget")
    op.drop_index(op.f("ix_anaf_record_siruta"), table_name="anaf_record")
    op.drop_table("anaf_record")
    op.drop_index(op.f("ix_place_parent"), table_name="place")
    op.drop_index(op.f("ix_place_kind"), table_name="place")
    op.drop_index(op.f("ix_place_county"), table_name="place")
    op.drop_table("place")
