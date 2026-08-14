"""Admin-only user management.

No DELETE by design: `event_logs` and `auth_sessions` reference users, so
hard deletion either cascades away audit history or fails on a foreign
key. Deactivation is the supported removal.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session, require_role
from recruiter.auth.passwords import hash_password
from recruiter.models import AuthSession, Role, User
from recruiter.schemas.user import PasswordSet, UserAdminRead, UserCreate, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


async def _active_admin_count(session: AsyncSession, *, excluding: int) -> int:
    return (await session.execute(
        select(func.count())
        .select_from(User)
        .where(User.role == Role.ADMIN, User.is_active.is_(True), User.id != excluding)
    )).scalar_one()


@router.get("", response_model=list[UserAdminRead])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(Role.ADMIN)),
) -> list[UserAdminRead]:
    rows = (await session.execute(select(User).order_by(User.email))).scalars().all()
    return [UserAdminRead.model_validate(r) for r in rows]


@router.post("", response_model=UserAdminRead, status_code=201)
async def create_user(
    payload: UserCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(Role.ADMIN)),
) -> UserAdminRead:
    email = payload.email.strip().lower()
    if (await session.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="a user with that email already exists")
    user = User(
        email=email, name=payload.name, role=payload.role, is_active=True,
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    await session.commit()
    return UserAdminRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserAdminRead)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_role(Role.ADMIN)),
) -> UserAdminRead:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    if payload.is_active is False and user.id == actor.id:
        raise HTTPException(status_code=409, detail="you cannot deactivate yourself")

    loses_admin = (
        user.role == Role.ADMIN
        and user.is_active
        and (payload.role not in (None, Role.ADMIN) or payload.is_active is False)
    )
    if loses_admin and await _active_admin_count(session, excluding=user.id) == 0:
        raise HTTPException(
            status_code=409,
            detail="this is the last active admin — promote another admin first",
        )

    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if payload.is_active is False:
            # Deactivation must bite now, not at cookie expiry.
            await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    await session.commit()
    return UserAdminRead.model_validate(user)


@router.post("/{user_id}/password", status_code=204)
async def reset_password(
    user_id: int,
    payload: PasswordSet,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(Role.ADMIN)),
) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.password_hash = hash_password(payload.password)
    # A reset exists to cut off access; old cookies must not survive it.
    await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    await session.commit()
