from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    database_url: str = "postgresql+psycopg://passport:passport@localhost:5432/passport"
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "passport-pdfs"
    minio_auto_create_bucket: bool = True
    max_upload_mb: int = 20
    worker_poll_seconds: float = 1.0
    database_retry_seconds: float = 3.0
    stale_job_seconds: int = 300
    sweeper_interval_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
