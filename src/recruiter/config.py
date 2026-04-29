from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RECRUITER_", extra="ignore")

    database_url: str = "postgresql+asyncpg://recruiter:recruiter@localhost:5432/recruiter"
    settings_key: str = "dev-only-32-byte-key-replace-me!!"  # 32 bytes
    resume_storage_path: str = "./var/resumes"
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()
