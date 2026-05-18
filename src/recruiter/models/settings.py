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
    # Stored LinkedIn `li_at` session cookie (encrypted) + a timestamp for
    # display so the UI can warn when the cookie is old / probably stale.
    # The password used to acquire this cookie is NEVER persisted — only
    # the resulting cookie is.
    linkedin_li_at_enc: Mapped[str | None] = mapped_column(String)
    linkedin_li_at_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Opt-in: when set, the backend will auto-re-login if it detects the
    # cookie has expired or been challenged. NULL on either field
    # disables auto-reconnect; the user must reconnect via the UI.
    # email is stored plaintext (low sensitivity, needed to drive the
    # form). password is encrypted via the same `settings_cipher` used
    # for the LLM/search API keys.
    linkedin_email: Mapped[str | None] = mapped_column(String(320))
    linkedin_password_enc: Mapped[str | None] = mapped_column(String)
    # Apify API key (encrypted). When set, LinkedIn URL adds are
    # routed through Apify first, with the Playwright path as the
    # fallback. ~$0.01/profile at apify.com. (Proxycurl was the
    # previous tenant of this slot but shut down in 2025 after a
    # LinkedIn lawsuit.)
    apify_api_key_enc: Mapped[str | None] = mapped_column(String)
    # Apify actor slug (`username/actor-name`). Plain text — actor IDs
    # are not secrets. The default `dev_fusion/...` actor requires a
    # paid Apify plan for API access; users on the free plan should
    # swap to a different actor here. The renderer in
    # `recruiter.sourcing.apify` handles common shape variations
    # (`experiences`/`positions`, `educations`/`education`, etc.).
    apify_actor_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
