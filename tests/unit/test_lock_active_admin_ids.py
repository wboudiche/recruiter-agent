"""Direct, deterministic proof that `_lock_active_admin_ids` actually
closes the TOCTOU window in `update_user`'s last-active-admin guard,
rather than merely narrowing it.

A plain COUNT here would let two concurrent requests demoting two
DIFFERENT admins each read a snapshot count over the OTHER (disjoint)
admin row, see "still 1 left", and both pass and commit — zero active
admins, un-recoverable in-app. This test drives two independent DB
sessions (real connections against the same Postgres instance, not two
statements on one session — locks are per-transaction, so reusing one
session would never contend with itself) through the exact interleaving
that causes the bug, and proves PostgreSQL's row lock actually blocks
the second transaction, and that once unblocked it sees the FIRST
transaction's committed write rather than a stale pre-commit snapshot.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from recruiter.api.users import _lock_active_admin_ids
from recruiter.auth.passwords import hash_password
from recruiter.models import Role, User


@pytest.mark.asyncio
async def test_second_transaction_blocks_then_sees_first_transactions_commit(
    pg_dsn: str, db_session_with_schema: AsyncSession,
) -> None:
    admin_a = User(
        email="lock-a@acme.com", role=Role.ADMIN, is_active=True,
        password_hash=hash_password("pw"),
    )
    admin_b = User(
        email="lock-b@acme.com", role=Role.ADMIN, is_active=True,
        password_hash=hash_password("pw"),
    )
    db_session_with_schema.add_all([admin_a, admin_b])
    await db_session_with_schema.commit()

    engine2 = create_async_engine(pg_dsn)
    Session2 = async_sessionmaker(engine2, expire_on_commit=False)
    try:
        # Transaction 1: lock the whole active-admin set and hold the
        # transaction open (no commit yet) — mirrors update_user's
        # in-flight request for admin A demoting/deactivating admin B.
        locked_1 = await _lock_active_admin_ids(db_session_with_schema)
        assert locked_1 == {admin_a.id, admin_b.id}

        async with Session2() as session2:
            # Transaction 2: the concurrent request for admin B doing the
            # same to admin A. It wants the same row set, so it must block
            # on transaction 1's still-open lock.
            task2 = asyncio.create_task(_lock_active_admin_ids(session2))
            await asyncio.sleep(0.3)
            assert not task2.done(), (
                "transaction 2 should still be blocked on transaction 1's "
                "row lock — if it isn't, the two requests aren't actually "
                "contending for the same rows and the race is still open"
            )

            # Transaction 1 demotes admin_b and commits, releasing its locks.
            admin_b.role = Role.VIEWER
            await db_session_with_schema.commit()

            # Transaction 2 must now unblock, and must see admin_b's
            # COMMITTED new role — not the pre-commit snapshot where
            # admin_b still counted as an active admin. This is the
            # PostgreSQL EvalPlanQual re-check that makes the fix correct
            # rather than merely serializing on a stale read.
            locked_2 = await asyncio.wait_for(task2, timeout=5)
            assert locked_2 == {admin_a.id}
            await session2.commit()
    finally:
        await engine2.dispose()
