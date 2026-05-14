"""hash session tokens — invalidate existing plaintext-token rows

Revision ID: 7c8a3f1d2b94
Revises: eb0f5927f50a
Create Date: 2026-05-14 00:00:00.000000

Existing rows store the raw cookie token as the primary key. After this
upgrade, the application stores SHA-256(token) instead. Existing rows
are therefore unreachable; we delete them so users re-login cleanly
rather than leaving orphaned rows growing the table.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '7c8a3f1d2b94'
down_revision: Union[str, None] = 'eb0f5927f50a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM auth_sessions")


def downgrade() -> None:
    # Downgrade does not restore the deleted sessions; reverting the code
    # alone is sufficient since new logins will produce plaintext-token rows.
    pass
