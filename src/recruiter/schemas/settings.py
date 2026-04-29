from pydantic import BaseModel, ConfigDict


class SettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    default_llm_provider: str
    has_anthropic_api_key: bool
    local_llm_url: str | None
    model_overrides: dict
    has_google_oauth_tokens: bool
    has_smtp_config: bool
    recruiter_name: str | None
    recruiter_email: str | None
    monthly_llm_spend_cap_usd: int | None


class SettingsUpdate(BaseModel):
    default_llm_provider: str | None = None
    anthropic_api_key: str | None = None
    local_llm_url: str | None = None
    model_overrides: dict | None = None
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    monthly_llm_spend_cap_usd: int | None = None
