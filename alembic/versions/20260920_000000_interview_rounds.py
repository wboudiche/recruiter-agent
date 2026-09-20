"""add interview rounds: a second interview without rejecting the candidate

Revision ID: b8f3d1a20c47
Revises: a7d2c4f19e58
Create Date: 2026-09-20 00:00:00.000000

Before this, `scheduled` was reachable only from `invited`, and `invited`
only by sending an invitation from `validated` — so the sole path back to
a second interview ran through REJECTED, stamping a rejection on a
candidate the recruiter wanted to keep and re-sending them an invitation
email. Round-1 interviewers could never contribute again either: their
sheets are permanently submitted and cannot be removed from the panel.

Assignments become one row per interviewer PER ROUND. Existing rows are
round 1 and every application's current round is 1, so nothing in flight
changes meaning.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b8f3d1a20c47'
down_revision: Union[str, None] = 'a7d2c4f19e58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interview_assignments",
        sa.Column("round", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "applications",
        sa.Column("interview_round", sa.Integer(), nullable=False, server_default="1"),
    )
    # (application, user) was unique; it is now unique only WITHIN a round,
    # so the same interviewer can sit on round 1 and round 2.
    op.drop_constraint(
        "uq_interview_assignment_app_user", "interview_assignments", type_="unique",
    )
    op.create_unique_constraint(
        "uq_interview_assignment_app_user_round",
        "interview_assignments",
        ["application_id", "user_id", "round"],
    )


def downgrade() -> None:
    # Rows from any round past the first have no place in the old schema and
    # would violate the (application, user) constraint being restored.
    op.execute("DELETE FROM interview_assignments WHERE round > 1")
    op.drop_constraint(
        "uq_interview_assignment_app_user_round", "interview_assignments", type_="unique",
    )
    op.create_unique_constraint(
        "uq_interview_assignment_app_user", "interview_assignments",
        ["application_id", "user_id"],
    )
    op.drop_column("applications", "interview_round")
    op.drop_column("interview_assignments", "round")
