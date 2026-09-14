"""add interview_assignments: one feedback sheet per interviewer per application

Revision ID: a7d2c4f19e58
Revises: c4e1a90b7d32
Create Date: 2026-09-14 00:00:00.000000

Questions stay in applications.interview_kit (shared); this table holds
who interviews and their own answers/ratings/verdict. No data migration:
legacy per-question answers in the kit JSON are read but never written
again (see docs/superpowers/specs/2026-09-14-multi-interviewer-design.md).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a7d2c4f19e58'
down_revision: Union[str, None] = 'c4e1a90b7d32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(),
                  sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sheet", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("application_id", "user_id",
                            name="uq_interview_assignment_app_user"),
    )
    op.create_index("ix_interview_assignments_application_id",
                    "interview_assignments", ["application_id"])
    op.create_index("ix_interview_assignments_user_id",
                    "interview_assignments", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_interview_assignments_user_id", table_name="interview_assignments")
    op.drop_index("ix_interview_assignments_application_id", table_name="interview_assignments")
    op.drop_table("interview_assignments")
