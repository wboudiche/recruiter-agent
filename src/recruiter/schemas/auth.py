from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    """Public projection of `User`. NEVER add `sub`, `issuer`, or other IdP
    correlation keys — they're internal identifiers and must not leak to
    the client. `last_login_at` is also internal telemetry, not user-facing."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None
    picture: str | None
