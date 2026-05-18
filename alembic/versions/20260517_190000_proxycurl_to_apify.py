"""rename settings.proxycurl_api_key_enc → apify_api_key_enc

Revision ID: e7a1b3c9d2f5
Revises: d8e7f3a1c9b4
Create Date: 2026-05-17 19:00:00.000000

Proxycurl shut down in 2025 after a LinkedIn lawsuit. We're replacing
the commercial-provider slot with Apify (dev_fusion/linkedin-profile-
scraper actor, ~$0.01/profile). The column rename keeps the encrypted-
key storage path identical — only the encrypted value's *meaning*
changes (Proxycurl key → Apify key). Any value persisted under the old
name is dropped: a stale Proxycurl key is worthless now anyway.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e7a1b3c9d2f5'
down_revision: Union[str, None] = 'd8e7f3a1c9b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("settings", "proxycurl_api_key_enc")
    op.add_column(
        "settings",
        sa.Column("apify_api_key_enc", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("settings", "apify_api_key_enc")
    op.add_column(
        "settings",
        sa.Column("proxycurl_api_key_enc", sa.String(), nullable=True),
    )
