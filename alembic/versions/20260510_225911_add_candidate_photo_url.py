"""add candidate photo_url

Revision ID: eb0f5927f50a
Revises: dfe54f9cb30b
Create Date: 2026-05-10 22:59:11.366245

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'eb0f5927f50a'
down_revision: Union[str, None] = 'dfe54f9cb30b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("photo_url", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidates", "photo_url")
