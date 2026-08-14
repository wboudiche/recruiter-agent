"""The migration must leave a working deployment working: existing users
keep full access, and the env account becomes a real, usable admin row."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.auth.passwords import verify_password
from recruiter.models import Role, User


@pytest.mark.asyncio
async def test_columns_exist_with_working_defaults(
    db_session_with_schema: AsyncSession,
) -> None:
    user = User(email="a@acme.com", role=Role.RECRUITER)
    db_session_with_schema.add(user)
    await db_session_with_schema.commit()

    fetched = (await db_session_with_schema.execute(
        select(User).where(User.email == "a@acme.com")
    )).scalar_one()

    assert fetched.role == Role.RECRUITER
    assert fetched.is_active is True
    assert fetched.password_hash is None


@pytest.mark.asyncio
async def test_password_hash_roundtrips_through_the_column(
    db_session_with_schema: AsyncSession,
) -> None:
    from recruiter.auth.passwords import hash_password

    db_session_with_schema.add(
        User(email="b@acme.com", role=Role.ADMIN, password_hash=hash_password("s3cret")),
    )
    await db_session_with_schema.commit()

    fetched = (await db_session_with_schema.execute(
        select(User).where(User.email == "b@acme.com")
    )).scalar_one()

    assert verify_password("s3cret", fetched.password_hash) is True
    assert verify_password("wrong", fetched.password_hash) is False
