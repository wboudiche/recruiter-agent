"""Admin-only user management.

No DELETE by design: `event_logs` and `auth_sessions` reference users, so
hard deletion either cascades away audit history or fails on a foreign
key. Deactivation is the supported removal.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.api.deps import get_session, require_role
from recruiter.auth.passwords import hash_password
from recruiter.models import AuthSession, Role, User
from recruiter.schemas.user import PasswordSet, UserAdminRead, UserCreate, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])

# Privilege changes are logged here because `event_logs` cannot hold them:
# its FK is `application_id`, so it models application events only. Role is
# what gates access to the stored API keys, LinkedIn cookie and SMTP
# credentials, so "who promoted whom, and when" needs to survive somewhere
# an operator can read it. Until a user-scoped audit table exists, the
# application log is that somewhere — every line names the acting admin and
# the target so the two can be told apart after the fact.
logger = logging.getLogger(__name__)


async def _lock_active_admin_ids(session: AsyncSession) -> set[int]:
    """Lock every currently-active-admin row FOR UPDATE and return their ids.

    A plain COUNT here is a TOCTOU race: two concurrent requests demoting
    two DIFFERENT admins would each read a snapshot count over the OTHER
    (disjoint) admin row and both see "still >= 1 left", so both pass and
    commit — zero active admins. Locking the id (excluding neither) means
    both requests contend for the SAME row set: the second blocks until
    the first commits, and PostgreSQL's post-unblock re-check (EvalPlanQual)
    drops any row that no longer matches the WHERE clause once it sees the
    first request's write — so the second request's `locked_ids` reflects
    the first request's committed change, not a stale pre-transaction read.
    This only narrows (rather than closes) the window if the lock is taken
    on a subset of the rows a concurrent request could also change; taking
    it on the *full* active-admin set — not "excluding this one target" —
    is what makes the two requests actually contend with each other.

    Returns ids rather than a count because PostgreSQL rejects
    `SELECT count(*) ... FOR UPDATE` ("FOR UPDATE is not allowed with
    aggregate functions"), so the count has to happen in Python.
    """
    rows = (await session.execute(
        select(User.id)
        .where(User.role == Role.ADMIN, User.is_active.is_(True))
        .with_for_update()
    )).scalars().all()
    return set(rows)


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
    actor: User = Depends(require_role(Role.ADMIN)),
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
    logger.info(
        "user created: %s (id=%s) with role %s by admin id=%s",
        user.email, user.id, user.role.value, actor.id,
    )
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

    wants_to_leave_admin = payload.role not in (None, Role.ADMIN) or payload.is_active is False
    if wants_to_leave_admin:
        # Lock (and re-read) the active-admin set now, rather than trusting
        # `user.role`/`user.is_active` fetched above — those could already
        # be stale if another request changed this same row in between.
        locked_admin_ids = await _lock_active_admin_ids(session)
        loses_admin = user.id in locked_admin_ids
        if loses_admin and len(locked_admin_ids - {user.id}) == 0:
            raise HTTPException(
                status_code=409,
                detail="this is the last active admin — promote another admin first",
            )

    # `Role(...)` normalisation, not `.value`: the column is a plain
    # String, so a row loaded from the DB carries a `str` here even though
    # the attribute is typed `Mapped[Role]`. Comparisons still work (Role
    # subclasses str) but `.value` would raise AttributeError.
    previous_role = Role(user.role).value
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if payload.is_active is False:
            # Deactivation must bite now, not at cookie expiry.
            await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    await session.commit()

    if payload.role is not None and payload.role.value != previous_role:
        logger.info(
            "role changed: user id=%s (%s) %s -> %s by admin id=%s",
            user.id, user.email, previous_role, payload.role.value, actor.id,
        )
    if payload.is_active is not None:
        logger.info(
            "user id=%s (%s) %s by admin id=%s",
            user.id, user.email,
            "reactivated" if payload.is_active else "deactivated, sessions revoked",
            actor.id,
        )
    return UserAdminRead.model_validate(user)


@router.post("/{user_id}/password", status_code=204)
async def reset_password(
    user_id: int,
    payload: PasswordSet,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_role(Role.ADMIN)),
) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.password_hash = hash_password(payload.password)
    # A reset exists to cut off access; old cookies must not survive it.
    await session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    await session.commit()
    logger.info(
        "password reset for user id=%s (%s) by admin id=%s, sessions revoked",
        user.id, user.email, actor.id,
    )
