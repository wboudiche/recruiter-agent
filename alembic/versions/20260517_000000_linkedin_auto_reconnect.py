"""add settings.linkedin_email + linkedin_password_enc (auto-reconnect)

Revision ID: c5b2e9a4f8d1
Revises: a4f8e1c9d3b7
Create Date: 2026-05-17 00:00:00.000000

Two opt-in columns for the LinkedIn auto-reconnect flow. When both are
populated, the LinkedIn fetcher will re-acquire the `li_at` cookie
automatically on expiry instead of asking the user to reconnect
manually. NULL on either field = today's manual-reconnect behaviour.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c5b2e9a4f8d1'
down_revision: Union[str, None] = 'a4f8e1c9d3b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("linkedin_email", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "settings",
        sa.Column("linkedin_password_enc", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("settings", "linkedin_password_enc")
    op.drop_column("settings", "linkedin_email")
