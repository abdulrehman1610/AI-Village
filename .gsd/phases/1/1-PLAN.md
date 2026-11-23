---
phase: 1
plan: 1
wave: 1
depends_on: []
files_modified:
  - .gitignore
  - .env.example
  - backend/pyproject.toml
  - backend/app/__init__.py
  - backend/app/config.py
  - backend/sim/__init__.py
  - backend/api/__init__.py
  - backend/tests/__init__.py
  - backend/tests/test_config.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "Python 3.12 backend package installs cleanly with FastAPI, Uvicorn, Pydantic v2, pytest, ruff, and mypy"
    - "Configuration loads offline from environment or defaults with zero committed secrets"
    - "Backend test runner, linter, and static type checker pass on the scaffold"
  artifacts:
    - ".gitignore ignores .env, .venv, __pycache__, node_modules, dist, and sqlite files"
    - ".env.example documents SIM_TICK_SECONDS, SIM_SEED, MAP_PATH, CORS_ORIGINS, and LLM_PROVIDER"
    - "backend/pyproject.toml defines project dependencies and strict ruff/mypy/pytest settings"
    - "backend/app/config.py defines Settings via pydantic-settings"
    - "backend/tests/test_config.py tests config defaults and map path resolution offline"
  key_links:
    - "backend/app/config.py resolves default MAP_PATH to frontend/public/assets/map.json relative to repo root"
---

# Plan 1.1: Backend Python 3.12 / FastAPI Scaffold & Root Config

## Objective
Initialize the repository root configuration (`.gitignore`, `.env.example`) and scaffold the Python 3.12 FastAPI backend package (`backend/pyproject.toml`, `backend/app/config.py`, package markers, and initial config test) so all subsequent simulation, pathfinding, and API plans have a verified, strictly typed environment.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/REQUIREMENTS.md

## Tasks

<task type="auto">
  <name>Initialize root repo config and backend Python package</name>
  <files>
    .gitignore
    .env.example
    backend/pyproject.toml
  </files>
  <action>
    Create the root `.gitignore`, `.env.example`, and `backend/pyproject.toml`, then install the backend environment locally.

    Steps:
    1. Create `.gitignore` ignoring Python artifacts (`__pycache__/`, `*.py[cod]`, `.venv/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`), Node/Vite artifacts (`node_modules/`, `frontend/dist/`, `.vite/`), secrets (`.env`, `.env.local`), runtime DB/logs (`*.db`, `*.sqlite*`, `logs/*.jsonl`), and OS files (`.DS_Store`, `Thumbs.db`).
    2. Create `.env.example` with safe non-secret defaults: `APP_ENV=development`, `SIM_TICK_SECONDS=1.0`, `SIM_SPEED=1`, `SIM_SEED=42`, `SIM_AUTO_START=true`, `MAP_PATH=`, `CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`, `LLM_PROVIDER=mock`, `GEMINI_API_KEY=your_gemini_api_key_here`.
    3. Create `backend/pyproject.toml` targeting `requires-python = ">=3.12"`, project name `ai-village-backend`, runtime dependencies (`fastapi>=0.115.0`, `uvicorn[standard]>=0.32.0`, `pydantic>=2.9.0`, `pydantic-settings>=2.6.0`, `websockets>=13.0`), and `[project.optional-dependencies] dev` (`pytest>=8.3.0`, `pytest-asyncio>=0.24.0`, `httpx>=0.27.0`, `ruff>=0.7.0`, `mypy>=1.13.0`).
    4. Configure `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `pythonpath = ["."]`, `asyncio_mode = "auto"`), `[tool.ruff]` (`line-length = 100`, `target-version = "py312"`, `select = ["E", "F", "I", "UP", "B"]`), and `[tool.mypy]` (`python_version = "3.12"`, `strict = true`, `warn_unused_configs = true`, plus `[[tool.mypy.overrides]]` with `module = ["tests.*"]`, `disallow_untyped_defs = false`, `disallow_untyped_decorators = false` so `app/`, `sim/`, `api/` remain strictly typed without pytest decorator noise).
    5. Provision the virtual environment in `backend/`: run `uv --directory backend sync --extra dev` (or if `uv` is unavailable, create `backend/.venv` with `python -m venv backend/.venv` and install editable `[dev]` with pip).

    AVOID: Putting real API keys in `.env.example` or chaining shell commands with `&&` (PowerShell 5.1 rejects `&&`).
    USE: Single commands per invocation and `pydantic-settings` for environment configuration.
  </action>
  <verify>
    uv --directory backend run python -c "import fastapi, pydantic, pydantic_settings, httpx, pytest; print('deps_ok')"
  </verify>
  <done>
    `.gitignore`, `.env.example`, and `backend/pyproject.toml` exist, and importing `fastapi`, `pydantic`, `pydantic_settings`, `httpx`, and `pytest` inside `backend/.venv` prints `deps_ok`.
  </done>
</task>

<task type="auto">
  <name>Create backend package structure, Settings config, and unit test</name>
  <files>
    backend/app/__init__.py
    backend/app/config.py
    backend/sim/__init__.py
    backend/api/__init__.py
    backend/tests/__init__.py
    backend/tests/test_config.py
  </files>
  <action>
    Create the backend subpackage markers, typed `Settings` module, and offline configuration unit tests.

    Steps:
    1. Create empty package `__init__.py` files in `backend/app/`, `backend/sim/`, `backend/api/`, and `backend/tests/`.
    2. Implement `backend/app/config.py` with `REPO_ROOT = Path(__file__).resolve().parents[2]` and `DEFAULT_MAP_PATH = REPO_ROOT / "frontend" / "public" / "assets" / "map.json"`.
    3. Define `Settings(BaseSettings)` using `model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")`:
       - `app_env: str = "development"`
       - `sim_tick_seconds: float = 1.0`
       - `sim_speed: int = 1`
       - `sim_seed: int = 42`
       - `sim_auto_start: bool = True`
       - `map_path: str = ""`
       - `cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"`
       - `llm_provider: str = "mock"`
       - Helper method `resolved_map_path(self) -> Path` returning `Path(self.map_path)` when non-empty else `DEFAULT_MAP_PATH`, and `parsed_cors_origins(self) -> list[str]` splitting `cors_origins` on commas cleanly.
    4. Export `get_settings() -> Settings` factory function.
    5. Create `backend/tests/test_config.py` testing default `Settings()` values (`sim_tick_seconds == 1.0`, `sim_seed == 42`, `llm_provider == "mock"`), `resolved_map_path()` default pointing to `frontend/public/assets/map.json`, custom `map_path` override, and `parsed_cors_origins()` parsing.

    AVOID: Duplicating map JSON across `backend/` and `frontend/` (which risks desyncing collision walls from visuals) or hardcoding absolute drive paths.
    USE: `Path(__file__).resolve().parents[2]` to locate the single canonical `frontend/public/assets/map.json` while supporting `MAP_PATH` override.
  </action>
  <verify>
    uv --directory backend run pytest tests/test_config.py -v
    uv --directory backend run ruff check .
    uv --directory backend run mypy app sim api tests
  </verify>
  <done>
    `test_config.py` passes offline with 0 failures, `ruff check .` exits 0, and `mypy app sim api tests` exits 0 with zero errors.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `.gitignore` and `.env.example` exist with zero secrets committed
- [ ] `backend/pyproject.toml` installs cleanly with `uv` / `.venv`
- [ ] `backend/app/config.py` passes `ruff`, `mypy`, and `pytest tests/test_config.py`

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in tests
