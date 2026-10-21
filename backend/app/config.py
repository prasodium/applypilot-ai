"""Application settings, read from environment variables / backend/.env. No secrets are hard-coded."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"  # development | production
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'applypilot.db'}"

    ai_provider: str = "mock"  # mock | openai_compatible
    ai_model: str = ""
    ai_api_key: SecretStr = SecretStr("")
    ai_base_url: str = "https://api.openai.com/v1"
    ai_timeout_seconds: float = 60.0

    frontend_origin: str = "http://localhost:5173"
    # Host headers the server answers to (DNS-rebinding defence). "testserver" is the in-process test client.
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "testserver"]
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    max_upload_mb: int = 10
    log_level: str = "INFO"

    browser_headless: bool = True
    # Where the local mock employer site is reachable. Only this origin has form filling/submission enabled.
    mock_employer_base_url: str = "http://127.0.0.1:8000/mock-employer"
    mount_mock_employer: bool = True  # development convenience; never mounted when app_env=production
    # Background bot scheduler: checks every `bot_tick_seconds` whether a run is due. It does nothing unless the user enabled the bot.
    bot_scheduler_enabled: bool = True
    bot_tick_seconds: float = 30.0
    # Serve the built frontend (frontend/dist) from the backend so one command runs everything. Ignored if the folder does not exist.
    serve_frontend: bool = True
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
