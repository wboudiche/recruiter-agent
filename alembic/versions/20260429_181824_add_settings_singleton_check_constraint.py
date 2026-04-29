"""add settings singleton check constraint

Revision ID: 867eb2efbf72
Revises: 93723269c59c
Create Date: 2026-04-29 18:18:24.954139

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '867eb2efbf72'
down_revision: Union[str, None] = '93723269c59c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint("ck_settings_singleton", "settings", "id = 1")


def downgrade() -> None:
    op.drop_constraint("ck_settings_singleton", "settings", type_="check")
