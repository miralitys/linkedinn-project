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
    lfas_llm_provider: str = "openrouter"
    lfas_llm_model: str = "anthropic/claude-sonnet-4.5"
    lfas_first_month_strict: int = 1
    lfas_host: str = "0.0.0.0"
    lfas_port: int = 8000
    linkedin_client_id: Optional[str] = None
    linkedin_client_secret: Optional[str] = None
    linkedin_redirect_uri: Optional[str] = None
    session_secret: Optional[str] = None  # для SessionMiddleware (OAuth state)
    session_https_only: bool = False  # Secure cookie для HTTPS (включать в production)
    # Вход по email и паролю (один пользователь из .env). Включено только если заданы оба значения.
    auth_enabled: bool = True
    auth_admin_email: Optional[str] = None  # логин (email)
    auth_admin_password: Optional[str] = None  # пароль
    # Вход через Google (OAuth 2.0). В Google Cloud Console: APIs & Services → Credentials → OAuth 2.0 Client ID (Web application), Redirect URI: https://your-domain/auth/google/callback
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: Optional[str] = None  # если пусто — строится из запроса (хост + /auth/google/callback)
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
