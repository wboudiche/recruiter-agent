"""add applications.rejection_reason + backfill from notes prefix

Revision ID: 3b2f4e7a9c1d
Revises: f1a4d6e8b3c2
Create Date: 2026-05-19 00:00:00.000000

Until now the Reject dialog stuffed the user-typed reason into
`applications.notes` with a `[REJECTED] ` prefix — invisible from the
UI. This migration promotes the reason to a first-class column and
backfills any existing notes that start with the prefix.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '3b2f4e7a9c1d'
down_revision: Union[str, None] = 'f1a4d6e8b3c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("rejection_reason", sa.String(), nullable=True),
    )
    # Backfill: any application with notes like '[REJECTED] <reason>'
    # gets the reason promoted to the new column and the prefix
    # stripped from notes. Use parameter-style for the regex so
    # Postgres treats the bracket as a literal.
    op.execute(
        """
        UPDATE applications
        SET
          rejection_reason = NULLIF(
            substring(notes FROM '^\\[REJECTED\\]\\s*(.*)$'),
            ''
          ),
          notes = NULLIF(
            regexp_replace(notes, '^\\[REJECTED\\]\\s*.*$', ''),
            ''
          )
        WHERE notes LIKE '[REJECTED]%';
        """
    )


def downgrade() -> None:
    # Re-fold the reason back into notes (best-effort) so we don't lose
    # data on a rollback.
    op.execute(
        """
        UPDATE applications
        SET notes = CASE
          WHEN notes IS NULL OR notes = '' THEN '[REJECTED] ' || rejection_reason
          ELSE '[REJECTED] ' || rejection_reason || E'\\n' || notes
        END
        WHERE rejection_reason IS NOT NULL;
        """
    )
    op.drop_column("applications", "rejection_reason")
