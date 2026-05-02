from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recruiter.config import get_config
from recruiter.models import User


async def maybe_resolve(session: AsyncSession) -> User | None:
    """Return a synthetic User if dev bypass is active, else None.

    Activation rule (safe by construction): the bypass requires
    `RECRUITER_DEV_AUTH_BYPASS` to be a non-empty email AND
    `RECRUITER_OIDC_ISSUER` to be empty/unset. A misconfigured prod
    that forgets to clear DEV_AUTH_BYPASS but DOES set OIDC_ISSUER
    falls through to the real OIDC path — the right failure mode.
    """
    cfg = get_config()
    if not cfg.dev_auth_bypass or cfg.oidc_issuer:
        return None
    email = cfg.dev_auth_bypass.strip().lower()
    user = (await session.execute(
        select(User).where(User.email == email)
    )).scalar_one_or_none()
    if user is not None:
        return user
    user = User(email=email, sub=f"dev-bypass:{email}", issuer="dev-bypass",
                name="Dev User")
    session.add(user)
    await session.commit()
    return user
