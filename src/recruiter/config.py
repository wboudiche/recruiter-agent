from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RECRUITER_", extra="ignore")

    database_url: str = "postgresql+asyncpg://recruiter:recruiter@localhost:5432/recruiter"
    settings_key: str = "dev-only-32-byte-key-replace-me!"  # 32 bytes (single trailing !)
    resume_storage_path: str = "./var/resumes"
    log_level: str = "INFO"
    local_llm_api_key: str | None = None
    chat_rate_limit: str = "30/minute"
    redis_url: str | None = None

    # OIDC SSO config — see docs/superpowers/specs/2026-05-02-oidc-auth-design.md
    oidc_issuer: str = ""                        # e.g. https://accounts.google.com
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "http://localhost:8765/api/auth/callback"
    oidc_allowed_domains: str = ""               # comma-separated, e.g. "acme.com,acme-corp.com"

    # Cookie / session config
    secure_cookies: bool = False                 # set true in HTTPS prod
    session_ttl_days: int = 7

    # Dev escape hatch — only active when oidc_issuer is empty
    dev_auth_bypass: str = ""                    # e.g. "walid@acme.com"

    # Seed "default account" — a single bootstrap user that can sign in with
    # email + password, alongside OIDC. Useful for docker-compose deploys
    # where setting up an IdP is overkill. Active when BOTH fields are set
    # AND dev_auth_bypass is empty (otherwise everyone is logged in as that
    # email regardless of credentials).
    default_account_email: str = ""
    default_account_password: str = ""

    # Comma-separated list for the Origin-header middleware
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # LinkedIn `li_at` session cookie. When set, the LinkedIn URL fetcher
    # uses headless Chromium to scrape the profile with this cookie
    # injected; otherwise it falls back to the GitHub-by-name enricher.
    # WARNING: this is the cookie of a real LinkedIn account — that
    # account bears the ToS-violation and ban risk.
    linkedin_li_at: str = ""


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()
