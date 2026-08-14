from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from recruiter.models import Role


class UserAdminRead(BaseModel):
    """Admin projection. Deliberately omits `password_hash` — a hash must
    never leave the server, not even to an admin."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str | None
    role: Role
    is_active: bool
    last_login_at: datetime | None


class UserCreate(BaseModel):
    # No EmailStr: it requires the optional `email-validator` dependency,
    # which isn't installed in this project (see schemas/auth.py's
    # PasswordLoginRequest for the same call).
    email: str = Field(min_length=3, max_length=320)
    name: str | None = None
    role: Role
    password: str = Field(min_length=8)


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class PasswordSet(BaseModel):
    password: str = Field(min_length=8)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)
