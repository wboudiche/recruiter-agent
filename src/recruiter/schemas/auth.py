from pydantic import BaseModel, ConfigDict, Field


class UserRead(BaseModel):
    """Public projection of `User`. NEVER add `sub`, `issuer`, or other IdP
    correlation keys — they're internal identifiers and must not leak to
    the client. `last_login_at` is also internal telemetry, not user-facing."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None
    picture: str | None


class PasswordLoginRequest(BaseModel):
    # Validated against the configured default-account email via constant-time
    # compare in the handler; no need for EmailStr (which requires an extra dep).
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)
    next: str | None = None


class AuthMethods(BaseModel):
    oidc: bool
    password: bool
