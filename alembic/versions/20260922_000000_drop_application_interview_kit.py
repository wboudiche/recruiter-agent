"""drop applications.interview_kit now that kits are rows

Revision ID: d4b8c1f60a37
Revises: c1a7e05b3f92
Create Date: 2026-09-22 00:00:00.000000

Split from the migration that created interview_kits so that revision is
lossless in both directions. Downgrading past THIS one rebuilds the blob
from the highest round's kit, which is lossy for an application whose
rounds have diverged — they cannot in phase 1, where every round is a
copy, but phase 3 must revisit this.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd4b8c1f60a37'
down_revision: Union[str, None] = 'c1a7e05b3f92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("applications", "interview_kit")


def downgrade() -> None:
    op.add_column("applications", sa.Column("interview_kit", sa.JSON(), nullable=True))
    op.execute("""
        UPDATE applications a
        SET interview_kit = k.blob
        FROM (
            SELECT DISTINCT ON (application_id) application_id,
                   json_build_object(
                       'status', status,
                       'error', error,
                       'generated_at', generated_at,
                       'generating_since', generating_since,
                       'closed_at', closed_at,
                       'submitted_at', submitted_at,
                       'questions', questions
                   ) AS blob
            FROM interview_kits
            ORDER BY application_id, round DESC
        ) k
        WHERE a.id = k.application_id
    """)
