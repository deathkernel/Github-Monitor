from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    github_token: str | None = None
    github_api_url: str = "https://api.github.com"
    poll_interval_seconds: int = 300
    detail_repo_limit: int = 15
    database_url: str = "sqlite:///./data/github_monitor.db"

    rate_soft_floor: int = 500
    rate_hard_floor: int = 100
    request_retry_limit: int = 3

    notification_webhook_url: str | None = None
    notification_min_severity: str = "warning"

    enable_write_actions: bool = False

    job_lease_seconds: int = 900

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
