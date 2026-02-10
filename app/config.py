# app/config.py
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings


def _normalize_database_url(url: str) -> str:
    """Supabase gives postgresql://; async SQLAlchemy needs postgresql+asyncpg://."""
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./lfas.db"
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    lfas_llm_provider: str = "openai"
    lfas_llm_model: str = "gpt-4o-mini"
    lfas_first_month_strict: int = 1
    lfas_host: str = "0.0.0.0"
    lfas_port: int = 8000
    linkedin_client_id: Optional[str] = None
    linkedin_client_secret: Optional[str] = None
    linkedin_redirect_uri: Optional[str] = None
    session_secret: Optional[str] = None  # для SessionMiddleware (OAuth state)
    playwright_user_data_dir: Optional[str] = None  # путь к профилю Chromium с залогиненным LinkedIn

    # RapidAPI — Fresh LinkedIn Profile Data
    rapidapi_key: Optional[str] = None
    rapidapi_host: str = "fresh-linkedin-profile-data.p.rapidapi.com"

    # Часовой пояс для отображения дат в UI (IANA, напр. America/Chicago)
    display_timezone: str = "America/Chicago"

    # Paths
    base_dir: Path = Path(__file__).resolve().parent.parent
    memory_dir: Path = base_dir / "memory"
    prompts_dir: Path = base_dir / "prompts"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        return _normalize_database_url(v) if isinstance(v, str) else v

    class Config:
        env_file = ".env"
        env_prefix = ""
        extra = "ignore"


settings = Settings()
