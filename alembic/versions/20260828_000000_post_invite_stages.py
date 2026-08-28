"""add interviewed/offer/hired stages + their timestamp columns

Revision ID: 8af6fd614b13
Revises: 7c1e9a4d2b58
Create Date: 2026-08-28 00:00:00.000000

The pipeline stopped at "scheduled" with no way for an application to
actually reach it, let alone go further. This adds the next three
stages after an interview is scheduled — interviewed, offer, hired —
plus a timestamp column per stage, mirroring validated_at/invited_at.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '8af6fd614b13'
down_revision: Union[str, None] = '7c1e9a4d2b58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE stage ADD VALUE IF NOT EXISTS 'interviewed'")
            op.execute("ALTER TYPE stage ADD VALUE IF NOT EXISTS 'offer'")
            op.execute("ALTER TYPE stage ADD VALUE IF NOT EXISTS 'hired'")

    op.add_column(
        "applications", sa.Column("interviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "applications", sa.Column("offer_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "applications", sa.Column("hired_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("applications", "hired_at")
    op.drop_column("applications", "offer_at")
    op.drop_column("applications", "interviewed_at")
    # Postgres has no clean way to remove an enum value; the added labels
    # are left in place on downgrade, matching the precedent set by the
    # 'enriching' stage migration.
