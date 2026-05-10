"""add enrichment columns

Revision ID: dfe54f9cb30b
Revises: 4354790745ac
Create Date: 2026-05-10 15:34:37.013377

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'dfe54f9cb30b'
down_revision: Union[str, None] = '4354790745ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # JSON column on applications, default NULL — bundle is absent until
    # the enrichment pipeline stage has populated it.
    op.add_column(
        "applications",
        sa.Column("enrichment", sa.JSON(), nullable=True),
    )
    # Per-job consent flag, default False (opt-in per Decision per spec).
    op.add_column(
        "jobs",
        sa.Column(
            "enrichment_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Add ENRICHING to the `stage` enum. Postgres-only ALTER TYPE.
    # SQLite tests treat the enum as a free-text string so this is a no-op
    # there; the model-level enum gains the value automatically.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE stage ADD VALUE IF NOT EXISTS 'enriching'")

    # Settings columns for enrichment master toggle + per-source keys.
    op.add_column(
        "settings",
        sa.Column(
            "enrichment_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("settings", sa.Column("enrichment_twitter_api_key_enc", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("enrichment_youtube_api_key_enc", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("enrichment_stackexchange_key_enc", sa.String(), nullable=True))
    # Per-source toggles. JSON dict keyed by source name → bool. Default
    # empty dict; the API layer fills missing keys with True (all-on).
    op.add_column(
        "settings",
        sa.Column(
            "enrichment_sources",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("settings", "enrichment_sources")
    op.drop_column("settings", "enrichment_stackexchange_key_enc")
    op.drop_column("settings", "enrichment_youtube_api_key_enc")
    op.drop_column("settings", "enrichment_twitter_api_key_enc")
    op.drop_column("settings", "enrichment_enabled")
    # Postgres has no clean way to remove an enum value; we leave the
    # 'enriching' label in place on downgrade. Acceptable per Alembic docs.
    op.drop_column("jobs", "enrichment_consent")
    op.drop_column("applications", "enrichment")
