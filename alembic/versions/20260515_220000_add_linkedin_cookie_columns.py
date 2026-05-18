"""add settings.linkedin_li_at_enc + linkedin_li_at_set_at

Revision ID: a4f8e1c9d3b7
Revises: 7c8a3f1d2b94
Create Date: 2026-05-15 22:00:00.000000

Persists the LinkedIn `li_at` session cookie acquired via the Playwright
login flow. The cookie is the only thing stored — the user's password is
ephemeral, held only during the connect call.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a4f8e1c9d3b7'
down_revision: Union[str, None] = '7c8a3f1d2b94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("linkedin_li_at_enc", sa.String(), nullable=True),
    )
    op.add_column(
        "settings",
        sa.Column("linkedin_li_at_set_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("settings", "linkedin_li_at_set_at")
    op.drop_column("settings", "linkedin_li_at_enc")
