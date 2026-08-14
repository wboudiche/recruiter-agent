"""users: password_hash, role, is_active + seed the first admin

Revision ID: 7c1e9a4d2b58
Revises: 3b2f4e7a9c1d
Create Date: 2026-08-14 00:00:00.000000

Until now the deployment supported exactly one human: the password login
compared against a single env pair and User rows only came from OIDC.
This adds per-user credentials and roles.

Existing rows are backfilled to `admin` deliberately — those users were
unrestricted before this migration, and silently demoting them to viewer
would break a working deployment on upgrade.
"""
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '7c1e9a4d2b58'
down_revision: Union[str, None] = '3b2f4e7a9c1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("role", sa.String(32), nullable=True))
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # Backfill BEFORE the NOT NULL constraint, or existing rows reject it.
    op.execute("UPDATE users SET role = 'admin' WHERE role IS NULL")
    op.alter_column("users", "role", nullable=False)

    conn = op.get_bind()
    email = (os.environ.get("RECRUITER_DEFAULT_ACCOUNT_EMAIL") or "").strip().lower()
    password = os.environ.get("RECRUITER_DEFAULT_ACCOUNT_PASSWORD") or ""
    existing = conn.execute(sa.text("SELECT count(*) FROM users")).scalar_one()

    if not email or not password:
        if existing == 0:
            # Seeding nothing here leaves a deployment with zero accounts and,
            # without OIDC, no way in. Fail loudly instead of locking the
            # operator out silently.
            raise RuntimeError(
                "users/roles migration: no users exist and "
                "RECRUITER_DEFAULT_ACCOUNT_EMAIL/PASSWORD are unset — "
                "set them so a first admin can be seeded, then re-run."
            )
        return

    already = conn.execute(
        sa.text("SELECT count(*) FROM users WHERE lower(email) = :e"), {"e": email},
    ).scalar_one()
    if already:
        # Idempotent: an existing row (e.g. from a previous password login)
        # is promoted rather than duplicated.
        conn.execute(
            sa.text("UPDATE users SET role = 'admin', is_active = true "
                    "WHERE lower(email) = :e"),
            {"e": email},
        )
        return

    from recruiter.auth.passwords import hash_password

    conn.execute(
        sa.text(
            "INSERT INTO users (email, sub, issuer, name, role, is_active, password_hash) "
            "VALUES (:e, :sub, 'default', 'Admin', 'admin', true, :h)"
        ),
        {"e": email, "sub": f"default:{email}", "h": hash_password(password)},
    )


def downgrade() -> None:
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
    op.drop_column("users", "password_hash")
