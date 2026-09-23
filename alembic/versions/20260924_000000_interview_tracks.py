"""interview tracks: re-key templated kits, one track per interviewer per round

Revision ID: f3b7d2e8a915
Revises: e6f2a9c4b1d3
Create Date: 2026-09-24 00:00:00.000000

Phase 3 derives every kit's track key from its template: `t<template_id>`,
or `default` without one. Phase-2 kits built from a template were created
under `default`; they and their panel rows are re-keyed so every kit
follows the rule. An interviewer is on at most one track per round, so the
assignment unique key drops `track`. Every existing row is on `default`,
so no existing data can violate it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f3b7d2e8a915'
down_revision: Union[str, None] = 'e6f2a9c4b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Panel rows first, while their kit still reads `default`.
    op.execute(sa.text(
        "UPDATE interview_assignments AS a"
        " SET track = 't' || k.template_id"
        " FROM interview_kits AS k"
        " WHERE k.template_id IS NOT NULL AND k.track = 'default'"
        " AND a.application_id = k.application_id AND a.round = k.round"
        " AND a.track = 'default'"
    ))
    op.execute(sa.text(
        "UPDATE interview_kits SET track = 't' || template_id"
        " WHERE template_id IS NOT NULL AND track = 'default'"
    ))
    op.drop_constraint(
        "uq_interview_assignment_app_user_round_track", "interview_assignments",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_interview_assignment_app_user_round", "interview_assignments",
        ["application_id", "user_id", "round"],
    )


def downgrade() -> None:
    # Pre-phase-3 code reads one kit per round; refuse rather than lose one.
    multi = op.get_bind().execute(sa.text(
        "SELECT application_id, round FROM interview_kits"
        " GROUP BY application_id, round HAVING count(*) > 1 LIMIT 1"
    )).first()
    if multi is not None:
        raise RuntimeError(
            f"cannot downgrade: application {multi[0]} round {multi[1]} has more than "
            "one interview track; remove the extra tracks first"
        )
    op.execute(sa.text("UPDATE interview_assignments SET track = 'default'"))
    op.execute(sa.text("UPDATE interview_kits SET track = 'default'"))
    op.drop_constraint(
        "uq_interview_assignment_app_user_round", "interview_assignments", type_="unique",
    )
    op.create_unique_constraint(
        "uq_interview_assignment_app_user_round_track", "interview_assignments",
        ["application_id", "user_id", "round", "track"],
    )
