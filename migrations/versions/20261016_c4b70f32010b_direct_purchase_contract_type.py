"""direct purchase contract type

Revision ID: c4b70f32010b
Revises: b97c7f44a18b
Create Date: 2026-10-16 19:20:21.561217
"""

import sqlalchemy as sa
from alembic import op

revision = "c4b70f32010b"
down_revision = "b97c7f44a18b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "direct_purchase", sa.Column("contract_type_id", sa.SmallInteger(), nullable=True)
    )
    # The rows already held take the type their query asked for, as the parser now does.
    # The CASE keeps a body that is not JSON from being read as JSON: PostgreSQL does not
    # promise to test the conditions of a WHERE in order.
    op.execute(
        """
        UPDATE direct_purchase AS dp
        SET contract_type_id = asked.kind::smallint
        FROM (
            SELECT id, CASE WHEN request_body LIKE '{%'
                THEN request_body::jsonb ->> 'sysAcquisitionContractTypeId' END AS kind
            FROM source_document
            WHERE source = 'seap-direct'
        ) AS asked
        WHERE asked.id = dp.source_document_id AND asked.kind IN ('1', '2', '3')
        """
    )


def downgrade() -> None:
    op.drop_column("direct_purchase", "contract_type_id")
