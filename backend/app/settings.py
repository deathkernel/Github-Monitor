from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    github_token: str | None = None
    github_api_url: str = "https://api.github.com"
    poll_interval_seconds: int = 300
    detail_repo_limit: int = 15
    database_url: str = "sqlite:///./data/github_monitor.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
