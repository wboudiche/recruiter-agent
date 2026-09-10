"""add interview baseline (job) and interview kit (application) columns

Revision ID: c4e1a90b7d32
Revises: 8af6fd614b13
Create Date: 2026-09-10 00:00:00.000000

Interview kits: a per-job baseline of shared questions, and a per-application
kit holding the snapshotted baseline plus generated probes with answers and
ratings. Both JSON, matching criteria/score_breakdown/enrichment.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c4e1a90b7d32'
down_revision: Union[str, None] = '8af6fd614b13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("interview_baseline", sa.JSON(), nullable=True))
    op.add_column("applications", sa.Column("interview_kit", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "interview_kit")
    op.drop_column("jobs", "interview_baseline")
