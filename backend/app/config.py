from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_MAP_PATH: Path = REPO_ROOT / "frontend" / "public" / "assets" / "map.json"


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

    def resolved_map_path(self) -> Path:
        """Return the configured map path or the canonical frontend asset path."""
        configured = self.map_path.strip()
        return Path(configured) if configured else DEFAULT_MAP_PATH

    def parsed_cors_origins(self) -> list[str]:
        """Split the comma-separated CORS origins string into clean entries."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def get_settings() -> Settings:
    """Create and return a fresh application settings instance."""
    return Settings()
