"""Application configuration from environment variables."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings

DATA_DIR = Path(os.getenv("INVOICEFLOW_DATA_DIR", Path.home() / ".invoiceflow"))
WATCH_DIR = DATA_DIR / "watch"
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    database_url: str = f"sqlite+aiosqlite:///{DATA_DIR / 'invoiceflow.db'}"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 30
    debug: bool = False

    ollama_base_url: str = "http://10.0.3.144:11434"
    ollama_model: str = "qwen2.5:14b"

    watch_dir: str = str(WATCH_DIR)
    upload_dir: str = str(UPLOAD_DIR)
    export_dir: str = str(EXPORT_DIR)

    duplicate_threshold: float = 85.0
    webhook_url: str = ""

    model_config = {"env_prefix": "INVOICEFLOW_"}


settings = Settings()

for d in [DATA_DIR, WATCH_DIR, UPLOAD_DIR, EXPORT_DIR]:
    d.mkdir(parents=True, exist_ok=True)
