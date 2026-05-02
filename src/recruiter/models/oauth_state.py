from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class OAuthState(Base):
    """Transient OIDC login state — PKCE verifier + nonce + return URL.

    One row per in-flight login. Rows are deleted when the callback
    completes; orphans older than 10 minutes are reaped on lookup.
    """
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    pkce_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    next_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
