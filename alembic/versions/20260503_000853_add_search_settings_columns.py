"""add search settings columns

Revision ID: 4354790745ac
Revises: 3e3db7988a1a
Create Date: 2026-05-03 00:08:53.646688

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4354790745ac'
down_revision: Union[str, None] = '3e3db7988a1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("search_provider", sa.String(32), nullable=True))
    op.add_column("settings", sa.Column("search_api_key_enc", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("search_engine_id", sa.String(255), nullable=True))
    op.add_column("settings", sa.Column("github_token_enc", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("settings", "github_token_enc")
    op.drop_column("settings", "search_engine_id")
    op.drop_column("settings", "search_api_key_enc")
    op.drop_column("settings", "search_provider")
