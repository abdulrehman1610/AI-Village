from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_MAP_PATH: Path = REPO_ROOT / "frontend" / "public" / "assets" / "map.json"
DEFAULT_DB_PATH: Path = REPO_ROOT / "backend" / "ai_village.db"


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or defaults."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    sim_tick_seconds: float = 1.0
    sim_speed: int = 1
    sim_seed: int = 42
    sim_auto_start: bool = True
    map_path: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    llm_provider: str = "mock"
    database_url: str = ""
    embedding_provider: str = "auto"
    gemini_api_key: str = ""
    gemini_routine_model: str = "gemini-2.5-flash"
    gemini_planning_model: str = "gemini-2.5-pro"
    llm_daily_budget_usd: float = 0.50
    llm_daily_token_limit: int = 250_000
    llm_max_retries: int = 1
    retrieval_w_recency: float = 1.0
    retrieval_w_importance: float = 1.0
    retrieval_w_relevance: float = 1.0
    retrieval_decay_per_hour: float = 0.995
    retrieval_top_k: int = 8

    def resolved_map_path(self) -> Path:
        """Return the configured map path or the canonical frontend asset path."""
        configured = self.map_path.strip()
        return Path(configured) if configured else DEFAULT_MAP_PATH

    def resolved_database_url(self) -> str:
        """Return the configured async database URL or the canonical local SQLite URL."""
        configured = self.database_url.strip()
        return configured if configured else f"sqlite+aiosqlite:///{DEFAULT_DB_PATH.as_posix()}"

    def resolved_embedding_provider(self) -> Literal["mock", "local"]:
        """Resolve effective embedding provider ('mock' or 'local')."""
        normalized = self.embedding_provider.strip().lower()
        if normalized == "auto":
            return "mock" if self.llm_provider.strip().lower() == "mock" else "local"
        if normalized == "mock":
            return "mock"
        if normalized == "local":
            return "local"
        raise ValueError(
            f"Unsupported embedding_provider {self.embedding_provider!r}; "
            "expected 'auto', 'mock', or 'local'."
        )

    def parsed_cors_origins(self) -> list[str]:
        """Split the comma-separated CORS origins string into clean entries."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def get_settings() -> Settings:
    """Create and return a fresh application settings instance."""
    return Settings()
