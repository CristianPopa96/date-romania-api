"""Settings, read only from environment variables so any host can run the same image."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://dr:dr@localhost:5432/date_romania"

    # Any S3-compatible store: SeaweedFS locally, Hetzner, Cloudflare R2 or AWS later.
    s3_endpoint: str = "http://localhost:8333"
    s3_bucket: str = "raw"
    s3_access_key: str = "dr"
    s3_secret_key: str = "dr-secret"
    s3_region: str = "us-east-1"

    # Sent with every request to public sources, so publishers know who is calling.
    http_user_agent: str = "date-romania/0.1 (+https://github.com/CristianPopa96/date-romania-api)"


@lru_cache
def get_settings() -> Settings:
    return Settings()
