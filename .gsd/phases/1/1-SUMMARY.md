---
phase: 1
plan: 1
completed_at: 2026-11-23T23:55:15+05:00
duration_minutes: 6
status: complete
---

# Summary: Plan 1.1 — Backend Python 3.12 / FastAPI Scaffold & Root Config

## Results

- **Tasks:** 2/2 completed
- **Commits:** 2 (`da6b9f4`, `49fc3e8`)
- **Verification:** Passed (deps import, pytest 4/4, ruff check, mypy strict)

---

## Tasks Completed

| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Initialize root repo config and backend Python package | `da6b9f4` | ✅ Complete |
| 2 | Create backend package structure, Settings config, and unit test | `49fc3e8` | ✅ Complete |

---

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `.gitignore` | Created | Ignores Python caches/venvs/`*.egg-info/`, Node/Vite artifacts, `.env`/`.env.local` (preserving `.env.example`), DB/log files, and OS files |
| `.env.example` | Created | Documents safe non-secret defaults (`APP_ENV`, `SIM_TICK_SECONDS`, `SIM_SPEED`, `SIM_SEED`, `SIM_AUTO_START`, `MAP_PATH`, `CORS_ORIGINS`, `LLM_PROVIDER`, `GEMINI_API_KEY` placeholder) |
| `backend/pyproject.toml` | Created | Defines `ai-village-backend` dependencies (`fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `websockets`), `[dev]` tools (`pytest`, `pytest-asyncio`, `httpx`, `ruff`, `mypy`), setuptools flat-layout package discovery, and pytest/ruff/mypy config |
| `backend/app/__init__.py` | Created | Package marker for `app` |
| `backend/app/config.py` | Created | Defines `REPO_ROOT`, `DEFAULT_MAP_PATH`, `Settings(BaseSettings)`, `resolved_map_path()`, `parsed_cors_origins()`, and `get_settings()` |
| `backend/sim/__init__.py` | Created | Package marker for `sim` |
| `backend/api/__init__.py` | Created | Package marker for `api` |
| `backend/tests/__init__.py` | Created | Package marker for `tests` |
| `backend/tests/test_config.py` | Created | Offline unit tests for `Settings` defaults, `DEFAULT_MAP_PATH`, `MAP_PATH` overrides, and `parsed_cors_origins()` |

---

## Deviations Applied

- **[Rule 3 - Blocking] Local venv provisioning fallback (`uv` unavailable):** `uv` was not installed on the host, so `backend/.venv` was provisioned with `python -m venv backend/.venv` (Python 3.13.13) and editable dependencies were installed with `backend/.venv/Scripts/python.exe -m pip install -e "backend[dev]"`, matching the plan's explicit fallback path.
- **[Rule 3 - Blocking] Packaging & lint metadata alignment:** Added `[build-system]` (`setuptools.build_meta`) and `[tool.setuptools.packages.find]` (`include = ["app*", "sim*", "api*"]`) in `backend/pyproject.toml` plus `*.egg-info/` in `.gitignore` so flat-layout editable installation does not fail on multiple top-level packages, and placed `select = ["E", "F", "I", "UP", "B"]` under `[tool.ruff.lint]` for Ruff 0.17.6 compatibility.

---

## Verification

| Check | Status | Evidence |
|-------|--------|----------|
| Dependency import (`fastapi`, `pydantic`, `pydantic_settings`, `httpx`, `pytest`) | ✅ Pass | `backend/.venv/Scripts/python.exe -c "import fastapi, pydantic, pydantic_settings, httpx, pytest; print('deps_ok')"` → `deps_ok` (exit 0) |
| Config unit tests (`tests/test_config.py`) | ✅ Pass | `pytest tests/test_config.py -v` (cwd `backend/`) → `4 passed in 0.22s` (exit 0) |
| Ruff linter | ✅ Pass | `ruff check .` (cwd `backend/`) → `All checks passed!` (exit 0) |
| Mypy static type check | ✅ Pass | `mypy app sim api tests` (cwd `backend/`) → `Success: no issues found in 6 source files` (exit 0) |

---

## Deferred

- `pytest-asyncio` 1.5.0 emits a deprecation notice because `asyncio_default_fixture_loop_scope` is unset in `backend/pyproject.toml`; harmless now, can be set when async tests are introduced.
- Running `ruff check` from repo root (instead of `backend/` cwd) treats `app` as third-party unless `[tool.ruff.lint.isort] known-first-party = ["app", "sim", "api"]` is added in a future config refinement.
- Note that the workspace has pre-existing untracked GSD framework/root files (`.agent/`, `.agents/`, `.gemini/`, `PROJECT_RULES.md`, etc.) that were left untouched and unstaged.

---

## Metadata

- **Started:** 2026-11-23T23:49:13+05:00
- **Completed:** 2026-11-23T23:55:15+05:00
- **Duration:** ~6 minutes
