"""add interview templates, a job default, and kit template snapshots

Revision ID: e6f2a9c4b1d3
Revises: d4b8c1f60a37
Create Date: 2026-09-21 00:00:00.000000

Purely additive: every new column is nullable or defaulted, so there is
no backfill, existing kits keep behaving exactly as before (no template),
and the downgrade simply drops what this adds.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e6f2a9c4b1d3'
down_revision: Union[str, None] = 'd4b8c1f60a37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("questions", sa.JSON(), nullable=False,
                  server_default=sa.text("'[]'")),
        sa.Column("probe_mode", sa.String(length=16), nullable=False,
                  server_default="score_gaps"),
        sa.Column("include_job_questions", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "uq_interview_templates_active_name", "interview_templates", ["name"],
        unique=True, postgresql_where=sa.text("is_active"),
    )
    op.add_column("jobs", sa.Column(
        "default_interview_template_id", sa.Integer(),
        sa.ForeignKey("interview_templates.id", ondelete="SET NULL"),
        nullable=True,
    ))
    op.add_column("interview_kits", sa.Column(
        "template_id", sa.Integer(),
        sa.ForeignKey("interview_templates.id", ondelete="SET NULL"),
        nullable=True,
    ))
    op.add_column("interview_kits",
                  sa.Column("template_name", sa.String(length=128),
                            nullable=True))
    op.add_column("interview_kits",
                  sa.Column("template_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("interview_kits", "template_snapshot")
    op.drop_column("interview_kits", "template_name")
    op.drop_column("interview_kits", "template_id")
    op.drop_column("jobs", "default_interview_template_id")
    op.drop_index("uq_interview_templates_active_name",
                  table_name="interview_templates")
    op.drop_table("interview_templates")
