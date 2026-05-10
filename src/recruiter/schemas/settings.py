from pydantic import BaseModel, ConfigDict


class SmtpConfigInput(BaseModel):
    host: str
    port: int
    user: str
    password: str
    from_email: str
    use_starttls: bool = True


class SettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    default_llm_provider: str
    has_anthropic_api_key: bool
    local_llm_url: str | None
    has_local_llm_api_key: bool
    model_overrides: dict
    has_google_oauth_tokens: bool
    has_smtp_config: bool
    recruiter_name: str | None
    recruiter_email: str | None
    monthly_llm_spend_cap_usd: int | None
    search_provider: str | None = None
    search_engine_id: str | None = None
    has_search_api_key: bool = False
    has_github_token: bool = False
    enrichment_enabled: bool = False
    has_enrichment_twitter_api_key: bool = False
    has_enrichment_youtube_api_key: bool = False
    has_enrichment_stackexchange_key: bool = False
    enrichment_sources: dict[str, bool] = {}


class SettingsUpdate(BaseModel):
    default_llm_provider: str | None = None
    anthropic_api_key: str | None = None
    local_llm_url: str | None = None
    local_llm_api_key: str | None = None
    model_overrides: dict | None = None
    smtp_config: SmtpConfigInput | None = None
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    monthly_llm_spend_cap_usd: int | None = None
    search_provider: str | None = None
    search_api_key: str | None = None
    search_engine_id: str | None = None
    github_token: str | None = None
    enrichment_enabled: bool | None = None
    enrichment_twitter_api_key: str | None = None
    enrichment_youtube_api_key: str | None = None
    enrichment_stackexchange_key: str | None = None
    enrichment_sources: dict[str, bool] | None = None
