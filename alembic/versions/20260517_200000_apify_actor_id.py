"""add settings.apify_actor_id

Revision ID: f1a4d6e8b3c2
Revises: e7a1b3c9d2f5
Create Date: 2026-05-17 20:00:00.000000

Lets users swap the Apify actor without code changes. Useful because
some actors gate API access by plan tier (e.g.,
dev_fusion/linkedin-profile-scraper rejects free-plan API calls; the
user-facing fix is to point at a different actor instead of upgrading
the Apify plan).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f1a4d6e8b3c2'
down_revision: Union[str, None] = 'e7a1b3c9d2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("apify_actor_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("settings", "apify_actor_id")
