"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/invoiceflow"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 30
    debug: bool = False

    model_config = {"env_prefix": "INVOICEFLOW_"}


settings = Settings()
