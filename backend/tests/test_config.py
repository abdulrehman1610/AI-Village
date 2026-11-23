from pathlib import Path

from pytest import MonkeyPatch

from app.config import DEFAULT_MAP_PATH, REPO_ROOT, Settings, get_settings


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
