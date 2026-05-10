from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from recruiter.models.base import Base


class SettingsRow(Base):
    __tablename__ = "settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    default_llm_provider: Mapped[str] = mapped_column(String(32), default="anthropic")
    anthropic_api_key_enc: Mapped[str | None] = mapped_column(String)
    local_llm_url: Mapped[str | None] = mapped_column(String(2048))
    local_llm_api_key_enc: Mapped[str | None] = mapped_column(String)
    model_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    google_oauth_tokens_enc: Mapped[str | None] = mapped_column(String)
    smtp_config_enc: Mapped[str | None] = mapped_column(String)
    recruiter_name: Mapped[str | None] = mapped_column(String(255))
    recruiter_email: Mapped[str | None] = mapped_column(String(255))
    monthly_llm_spend_cap_usd: Mapped[int | None] = mapped_column(Integer)
    search_provider: Mapped[str | None] = mapped_column(String(32))
    search_api_key_enc: Mapped[str | None] = mapped_column(String)
    search_engine_id: Mapped[str | None] = mapped_column(String(255))
    github_token_enc: Mapped[str | None] = mapped_column(String)
    enrichment_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enrichment_twitter_api_key_enc: Mapped[str | None] = mapped_column(String)
    enrichment_youtube_api_key_enc: Mapped[str | None] = mapped_column(String)
    enrichment_stackexchange_key_enc: Mapped[str | None] = mapped_column(String)
    enrichment_sources: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
