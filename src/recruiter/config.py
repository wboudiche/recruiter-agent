from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RECRUITER_", extra="ignore")

    database_url: str = "postgresql+asyncpg://recruiter:recruiter@localhost:5432/recruiter"
    settings_key: str = "dev-only-32-byte-key-replace-me!"  # 32 bytes (single trailing !)
    resume_storage_path: str = "./var/resumes"
    log_level: str = "INFO"
    local_llm_api_key: str | None = None
    # Per-client rate limit on POST /api/applications/{id}/chat. Each chat
    # turn can drive multiple LLM calls (one per agent loop step), so the
    # cost ceiling matters even with a single user. SlowAPI string format,
    # e.g. "30/minute", "10/second". Set to "" to disable.
    chat_rate_limit: str = "30/minute"


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()
