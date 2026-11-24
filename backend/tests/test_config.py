from pathlib import Path

import pytest
from pytest import MonkeyPatch

from app.config import DEFAULT_DB_PATH, DEFAULT_MAP_PATH, REPO_ROOT, Settings, get_settings


def test_settings_defaults() -> None:
    """Verify safe offline defaults when no overrides are provided."""
    settings = Settings()

    assert settings.app_env == "development"
    assert settings.sim_tick_seconds == 1.0
    assert settings.sim_speed == 1
    assert settings.sim_seed == 42
    assert settings.sim_auto_start is True
    assert settings.map_path == ""
    assert settings.llm_provider == "mock"


def test_phase2_settings_defaults() -> None:
    """Verify Phase 2 database, embedding, LLM budget, and retrieval defaults."""
    settings = Settings()

    assert settings.database_url == ""
    assert settings.embedding_provider == "auto"
    assert settings.gemini_api_key == ""
    assert settings.gemini_routine_model == "gemini-2.5-flash"
    assert settings.gemini_planning_model == "gemini-2.5-pro"
    assert settings.llm_daily_budget_usd == 0.50
    assert settings.llm_daily_token_limit == 250_000
    assert settings.llm_max_retries == 1
    assert settings.retrieval_w_recency == 1.0
    assert settings.retrieval_w_importance == 1.0
    assert settings.retrieval_w_relevance == 1.0
    assert settings.retrieval_decay_per_hour == 0.995
    assert settings.retrieval_top_k == 8


def test_resolved_map_path_default() -> None:
    """Verify default map path points to the canonical frontend map asset."""
    settings = Settings()
    expected = REPO_ROOT / "frontend" / "public" / "assets" / "map.json"

    assert DEFAULT_MAP_PATH == expected
    assert settings.resolved_map_path() == expected


def test_resolved_map_path_override(monkeypatch: MonkeyPatch) -> None:
    """Verify MAP_PATH environment variable and constructor override resolution."""
    custom_path = "custom/village_map.json"
    monkeypatch.setenv("MAP_PATH", custom_path)

    env_settings = get_settings()
    assert env_settings.resolved_map_path() == Path(custom_path)

    direct_settings = Settings(map_path="  /tmp/override.json  ")
    assert direct_settings.resolved_map_path() == Path("/tmp/override.json")


def test_resolved_database_url_default_and_override(monkeypatch: MonkeyPatch) -> None:
    """Verify default SQLite URL resolution and explicit DATABASE_URL overrides."""
    expected_default = REPO_ROOT / "backend" / "ai_village.db"
    assert DEFAULT_DB_PATH == expected_default

    default_settings = Settings()
    assert default_settings.resolved_database_url() == (
        f"sqlite+aiosqlite:///{expected_default.as_posix()}"
    )

    blank_settings = Settings(database_url="   ")
    assert blank_settings.resolved_database_url() == (
        f"sqlite+aiosqlite:///{expected_default.as_posix()}"
    )

    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    env_settings = get_settings()
    assert env_settings.resolved_database_url() == "sqlite+aiosqlite:///:memory:"

    direct_settings = Settings(database_url="  sqlite+aiosqlite:///custom.db  ")
    assert direct_settings.resolved_database_url() == "sqlite+aiosqlite:///custom.db"


def test_resolved_embedding_provider() -> None:
    """Verify embedding provider auto-detection, explicit overrides, and invalid rejection."""
    assert (
        Settings(embedding_provider="auto", llm_provider="mock").resolved_embedding_provider()
        == "mock"
    )
    assert (
        Settings(embedding_provider=" AUTO ", llm_provider="gemini").resolved_embedding_provider()
        == "local"
    )
    assert (
        Settings(embedding_provider="local", llm_provider="mock").resolved_embedding_provider()
        == "local"
    )
    assert (
        Settings(embedding_provider=" MOCK ", llm_provider="gemini").resolved_embedding_provider()
        == "mock"
    )

    with pytest.raises(ValueError, match="Unsupported embedding_provider"):
        Settings(embedding_provider="invalid_provider").resolved_embedding_provider()


def test_parsed_cors_origins() -> None:
    """Verify comma-separated CORS origins are trimmed and empty items dropped."""
    default_settings = Settings()
    assert default_settings.parsed_cors_origins() == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    custom_settings = Settings(cors_origins=" http://example.com , , https://demo.local ")
    assert custom_settings.parsed_cors_origins() == [
        "http://example.com",
        "https://demo.local",
    ]
