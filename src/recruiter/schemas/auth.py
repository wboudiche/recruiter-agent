from pydantic import BaseModel, ConfigDict, Field

from recruiter.models import Role


class UserRead(BaseModel):
    """Public projection of `User`. NEVER add `sub`, `issuer`, or other IdP
    correlation keys — they're internal identifiers and must not leak to
    the client. `last_login_at` is also internal telemetry, not user-facing."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None
    picture: str | None
    # The client needs its own authorization level to render navigation.
    # This is NOT an IdP correlation key, so it does not violate the rule
    # above about `sub`/`issuer`. `is_active` is deliberately absent: an
    # inactive user cannot hold a session, so it would always be true.
    role: Role


class PasswordLoginRequest(BaseModel):
    # Validated against the configured default-account email via constant-time
    # compare in the handler; no need for EmailStr (which requires an extra dep).
    email: str = Field(min_length=3, max_length=320)
    # min_length=0: an unknown/OIDC-only account must still reach the handler
    # (even with an empty password) so it fails via the same 401 path as every
    # other bad credential, rather than a 422 that would carve out a distinct
    # response shape for the "empty password" case.
    password: str = Field(min_length=0, max_length=256)
    next: str | None = None


class AuthMethods(BaseModel):
    oidc: bool
    password: bool
