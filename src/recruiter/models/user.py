from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from recruiter.models.base import Base

if TYPE_CHECKING:
    from recruiter.models.session import AuthSession


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("issuer", "sub", name="uq_users_issuer_sub"),
        Index("ix_users_email", "email", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    sub: Mapped[str | None] = mapped_column(String(255))
    issuer: Mapped[str | None] = mapped_column(String(512))
    name: Mapped[str | None] = mapped_column(String(255))
    picture: Mapped[str | None] = mapped_column(String(2048))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ORM-side cascade mirrors the DB-level ON DELETE CASCADE on auth_sessions.user_id.
    # When the User is deleted, SQLAlchemy emits per-row DELETEs on auth_sessions, which
    # also expires the rows from the identity map (so session.get(AuthSession, ...) returns
    # None afterwards). The DB-level cascade is a belt-and-suspenders safeguard.
    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
