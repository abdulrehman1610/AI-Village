---
phase: 6
plan: 1
completed_at: 2026-11-26T00:25:00+05:00
duration_minutes: 6
---

# Summary: Plan 6.1 — Docker Containerization, Nginx Reverse Proxy & CI Packaging Gate

## Results
- 3 tasks completed
- All verifications passed (`ruff check .`, `mypy .`, `pytest -v` 121/121 passing)

## Tasks Completed
| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Create `.dockerignore`, `backend/Dockerfile`, and `docker-compose.yml` | `a6ad6b9` | ✅ |
| 2 | Create `frontend/nginx.conf` and multi-stage `frontend/Dockerfile` | `f8e1b59` | ✅ |
| 3 | Add Docker/Nginx route-parity contract test and CI Compose validation | `0a4c9b3` | ✅ |

## Deviations Applied
- `[Rule 1 - Bug]` In `backend/tests/test_docker_packaging.py`, FastAPI 0.165.0 stores `include_router(...)` routes inside `_IncludedRouter` wrappers (`original_router.routes` + `include_context`) rather than flat `APIRoute` entries directly in `app.routes`. Added `_iter_app_routes()` to recursively unwrap `_IncludedRouter` and nested mounts so dynamic route parity inspection verifies 100% of REST prefixes and `/ws` across FastAPI versions.

## Files Changed
- `.dockerignore` — excludes `.git`, `.gsd`, virtualenvs, Python/Vite caches, `frontend/node_modules`, `frontend/dist`, `.env*`, SQLite databases, runtime logs, and binary doc assets while keeping `backend/`, `frontend/`, `frontend/public/assets/map.json`, and `.env.example` available.
- `backend/Dockerfile` — `python:3.12-slim` image built from repo root context, installing dependencies with `--extra-index-url https://download.pytorch.org/whl/cpu`, baking `frontend/public/assets/map.json` to `/app/assets/map.json`, creating `/app/data` and `/app/logs`, setting `MAP_PATH`, `DATABASE_URL`, `REPLAY_LOG_DIR`, `LLM_PROVIDER=mock`, and `EMBEDDING_PROVIDER=auto`, and declaring a `/health` `HEALTHCHECK`.
- `docker-compose.yml` — orchestrates `backend` (`8000:8000`, `village_data:/app/data` directory volume for SQLite WAL, `./logs:/app/logs`, `${VAR:-default}` env overrides, `/health` healthcheck) and `frontend` (`5173:80`, `depends_on: backend: condition: service_healthy`).
- `frontend/nginx.conf` — proxies `/ws` with `Upgrade`/`Connection` mapping and `proxy_read_timeout 3600s` / `proxy_send_timeout 3600s`, proxies all 8 FastAPI REST prefixes (`health|world|agents|events|sim|relationships|metrics|replay`) to `http://backend:8000`, serves `/assets/` with `try_files $uri =404;`, and provides SPA fallback.
- `frontend/Dockerfile` — multi-stage `node:20-alpine` (`npm ci` + `npm run build`) to `nginx:1.27-alpine` serving `/usr/share/nginx/html` on port `80`.
- `backend/tests/test_docker_packaging.py` — stdlib + FastAPI offline contract tests validating `.dockerignore`, `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` directory mounts and `Settings` parity, and dynamic FastAPI-to-Nginx route parity.
- `.github/workflows/ci.yml` — added `docker-compose` job (`ubuntu-latest`, `timeout-minutes: 5`) validating `docker compose config --quiet` without altering existing `backend` or `frontend` jobs.

## Verification
- `backend/.venv/Scripts/python.exe -c "... DOCKER_CONFIG_OK"` (Task 1 check): ✅ Passed (`DOCKER_CONFIG_OK`)
- `backend/.venv/Scripts/python.exe -c "... FRONTEND_DOCKER_OK"` (Task 2 check): ✅ Passed (`FRONTEND_DOCKER_OK`)
- `backend/.venv/Scripts/ruff.exe check backend/tests/test_docker_packaging.py`: ✅ Passed (`All checks passed!`)
- `backend/.venv/Scripts/mypy.exe --config-file backend/pyproject.toml backend/tests/test_docker_packaging.py`: ✅ Passed (`Success: no issues found in 1 source file`)
- `backend/.venv/Scripts/pytest.exe -c backend/pyproject.toml --rootdir=backend -v backend/tests/test_docker_packaging.py`: ✅ Passed (`4 passed in 1.39s`)
- Full backend `ruff check .` (from `backend/`): ✅ Passed (`All checks passed!`)
- Full backend `mypy .` (from `backend/`): ✅ Passed (`Success: no issues found in 55 source files`)
- Full backend `pytest -v` (from `backend/`): ✅ Passed (`121 passed in 20.40s`)
- Host boundary note: Docker CLI is not installed on this local Windows host; live `docker compose config --quiet` validation runs in GitHub Actions CI (`ubuntu-latest`).

## Deferred
- Pre-existing unstaged newline modifications in `backend/api/__init__.py`, `backend/app/__init__.py`, `backend/sim/__init__.py`, `backend/tests/__init__.py` and untracked workspace/GSD framework files were left untouched outside Plan 6.1 scope.
