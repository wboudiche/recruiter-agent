"""add settings.proxycurl_api_key_enc

Revision ID: d8e7f3a1c9b4
Revises: c5b2e9a4f8d1
Create Date: 2026-05-17 18:00:00.000000

Optional commercial LinkedIn extraction provider. NULL = use the
Playwright path; non-NULL = Proxycurl first, Playwright as fallback.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd8e7f3a1c9b4'
down_revision: Union[str, None] = 'c5b2e9a4f8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("proxycurl_api_key_enc", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("settings", "proxycurl_api_key_enc")
