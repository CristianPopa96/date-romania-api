"""Settings, read only from environment variables so any host can run the same image."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # An empty variable counts as not set, so Compose can pass every setting through.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # Defaults use 127.0.0.1, not localhost: Compose publishes the ports on IPv4 only.
    database_url: str = "postgresql+psycopg://dr:dr@127.0.0.1:5432/date_romania"

    # Any S3-compatible store: SeaweedFS locally, Hetzner, Cloudflare R2 or AWS later.
    s3_endpoint: str = "http://127.0.0.1:8333"
    s3_bucket: str = "raw"
    s3_access_key: str = "dr"
    s3_secret_key: str = "dr-secret"
    s3_region: str = "us-east-1"

    # Sent with every request to public sources, so publishers know who is calling.
    http_user_agent: str = "date-romania/0.1 (+https://github.com/CristianPopa96/date-romania-api)"


@lru_cache
def get_settings() -> Settings:
    return Settings()
