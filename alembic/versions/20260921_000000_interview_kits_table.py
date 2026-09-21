"""move interview kits into their own table, keyed by (application, round, track)

Revision ID: c1a7e05b3f92
Revises: b8f3d1a20c47
Create Date: 2026-09-21 00:00:00.000000

The blob is left in place: this migration only copies out of it, so a
downgrade is lossless and the application keeps working at either
revision. Dropping applications.interview_kit is a separate migration
that runs once nothing reads it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c1a7e05b3f92'
down_revision: Union[str, None] = 'b8f3d1a20c47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_kits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(),
                  sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("track", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("generated_at", sa.String(), nullable=True),
        sa.Column("generating_since", sa.String(), nullable=True),
        sa.Column("closed_at", sa.String(), nullable=True),
        sa.Column("submitted_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("application_id", "round", "track",
                            name="uq_interview_kit_app_round_track"),
    )
    op.create_index("ix_interview_kits_application_id", "interview_kits", ["application_id"])

    op.add_column(
        "interview_assignments",
        sa.Column("track", sa.String(length=64), nullable=False, server_default="default"),
    )
    op.drop_constraint(
        "uq_interview_assignment_app_user_round", "interview_assignments", type_="unique",
    )
    op.create_unique_constraint(
        "uq_interview_assignment_app_user_round_track",
        "interview_assignments",
        ["application_id", "user_id", "round", "track"],
    )

    # One row per round from 1 to the application's current round, each a
    # copy. An application reopened into round 2 shares ONE kit today, and
    # round 1's submitted sheets resolve their answers against its question
    # ids — a single row at the live round would leave that feedback
    # pointing at a kit that does not exist.
    op.execute("""
        INSERT INTO interview_kits (
            application_id, round, track, questions, status, error,
            generated_at, generating_since, closed_at, submitted_at,
            created_at, updated_at
        )
        SELECT a.id,
               r.round,
               'default',
               COALESCE(a.interview_kit -> 'questions', '[]'::json),
               COALESCE(a.interview_kit ->> 'status', 'ready'),
               a.interview_kit ->> 'error',
               a.interview_kit ->> 'generated_at',
               a.interview_kit ->> 'generating_since',
               a.interview_kit ->> 'closed_at',
               a.interview_kit ->> 'submitted_at',
               now(), now()
        FROM applications a
        CROSS JOIN LATERAL generate_series(1, a.interview_round) AS r(round)
        WHERE a.interview_kit IS NOT NULL
    """)


def downgrade() -> None:
    # Lossless: applications.interview_kit was never touched.
    op.drop_constraint(
        "uq_interview_assignment_app_user_round_track", "interview_assignments", type_="unique",
    )
    op.create_unique_constraint(
        "uq_interview_assignment_app_user_round", "interview_assignments",
        ["application_id", "user_id", "round"],
    )
    op.drop_column("interview_assignments", "track")
    op.drop_index("ix_interview_kits_application_id", table_name="interview_kits")
    op.drop_table("interview_kits")
