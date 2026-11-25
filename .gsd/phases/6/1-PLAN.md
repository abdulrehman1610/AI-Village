---
phase: 6
plan: 1
wave: 1
depends_on: []
files_modified:
  - .dockerignore
  - backend/Dockerfile
  - docker-compose.yml
  - frontend/nginx.conf
  - frontend/Dockerfile
  - backend/tests/test_docker_packaging.py
  - .github/workflows/ci.yml
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "`backend/Dockerfile` builds from repo root context on `python:3.12-slim` using `--extra-index-url https://download.pytorch.org/whl/cpu`, bakes `frontend/public/assets/map.json` to `/app/assets/map.json`, creates `/app/data` and `/app/logs`, sets `MAP_PATH`, `DATABASE_URL`, `REPLAY_LOG_DIR`, and `LLM_PROVIDER=mock`, and declares a `/health` `HEALTHCHECK`"
    - "`frontend/nginx.conf` proxies `/ws` with WebSocket `Upgrade`/`Connection` headers and `proxy_read_timeout 3600s`, proxies all 8 FastAPI REST prefixes (`/health`, `/world`, `/agents`, `/events`, `/sim`, `/relationships`, `/metrics`, `/replay`) to `http://backend:8000`, and serves built Vite static assets + `/assets/*` via `frontend/Dockerfile`"
    - "`docker-compose.yml` wires `backend` (`8000:8000`, directory volume `village_data:/app/data` for SQLite WAL + `./logs:/app/logs` for JSONL replays, healthcheck, `${VAR:-default}` env overrides) and `frontend` (`5173:80`, `depends_on: backend: condition: service_healthy`), verified by `backend/tests/test_docker_packaging.py` and `docker compose config --quiet` in `.github/workflows/ci.yml`"
  artifacts:
    - ".dockerignore excludes build caches, node_modules, venvs, local SQLite DBs, .env, and runtime logs while preserving backend/, frontend/, and map.json"
    - "backend/Dockerfile packages the Python 3.12 FastAPI simulation backend with CPU-only PyTorch"
    - "frontend/nginx.conf defines WebSocket upgrade mapping and route parity across all FastAPI endpoints"
    - "frontend/Dockerfile implements a multi-stage node:20-alpine -> nginx:1.27-alpine production build"
    - "docker-compose.yml orchestrates backend and frontend for one-command execution"
    - "backend/tests/test_docker_packaging.py verifies container definitions, directory mounts, env var names, and FastAPI-to-Nginx route parity offline using stdlib only"
    - ".github/workflows/ci.yml adds a docker-compose-check job validating `docker compose config --quiet`"
  key_links:
    - "`backend/Dockerfile` `MAP_PATH=/app/assets/map.json`, `DATABASE_URL=sqlite+aiosqlite:////app/data/ai_village.db`, and `REPLAY_LOG_DIR=/app/logs` match `Settings` field names in `backend/app/config.py`"
    - "`frontend/nginx.conf` proxy locations cover 100% of `APIRoute` and `APIWebSocketRoute` prefixes registered on `create_app()` (`backend/api/rest.py`, `backend/api/ws.py`)"
    - "`docker-compose.yml` mounts `/app/data` as a directory volume (`village_data:/app/data`) rather than a single `.db` file so SQLite WAL `-wal`/`-shm` sidecar files work safely"
---

# Plan 6.1: Docker Containerization, Nginx Reverse Proxy & CI Packaging Gate

## Objective
Package AI Village for reproducible one-command execution via `Dockerfile`s, `frontend/nginx.conf`, `.dockerignore`, and `docker-compose.yml` (`REQ-16`). Because Docker CLI is not installed on the local Windows host, enforce structural and API-to-Nginx route parity via `backend/tests/test_docker_packaging.py` and validate Compose configuration natively inside `.github/workflows/ci.yml` (`ubuntu-latest`).

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/phases/6/RESEARCH.md
- backend/app/config.py
- backend/app/main.py
- backend/app/db.py
- backend/api/rest.py
- backend/api/ws.py
- backend/pyproject.toml
- frontend/vite.config.ts
- .env.example
- .github/workflows/ci.yml

## Tasks

<task type="auto">
  <name>Create .dockerignore, backend/Dockerfile, and docker-compose.yml</name>
  <files>
    .dockerignore
    backend/Dockerfile
    docker-compose.yml
  </files>
  <action>
    Author container packaging for the Python FastAPI backend and Compose stack, honoring exact `Settings` environment names in `backend/app/config.py`.

    Steps:
    1. Create `.dockerignore` excluding `.git`, `.gsd`, `**/.venv`, `**/venv`, `**/__pycache__`, `**/*.py[cod]`, `**/.pytest_cache`, `**/.mypy_cache`, `**/.ruff_cache`, `frontend/node_modules`, `frontend/dist`, `.env`, `.env.local`, `*.db`, `*.sqlite*`, `logs/*.jsonl`, and `docs/*.gif` (keep `backend/`, `frontend/`, `frontend/public/assets/`, `.env.example` accessible to build contexts).
    2. Create `backend/Dockerfile` designed for repo-root build context (`context: .`, `dockerfile: backend/Dockerfile`):
       - `FROM python:3.12-slim`
       - `WORKDIR /app`
       - Copy `backend/pyproject.toml` and `backend/` source packages (`app`, `sim`, `agents`, `memory`, `llm`, `api`), plus copy `frontend/public/assets/map.json` into `/app/assets/map.json`.
       - Run `python -m pip install --no-cache-dir --upgrade pip` and `python -m pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu .` so PyTorch uses lightweight CPU wheels matching `.github/workflows/ci.yml`.
       - Run `mkdir -p /app/data /app/logs`.
       - Set container `ENV` defaults:
         - `PYTHONUNBUFFERED=1`
         - `PYTHONDONTWRITEBYTECODE=1`
         - `MAP_PATH=/app/assets/map.json`
         - `DATABASE_URL=sqlite+aiosqlite:////app/data/ai_village.db`
         - `REPLAY_LOG_DIR=/app/logs`
         - `LLM_PROVIDER=mock`
         - `EMBEDDING_PROVIDER=auto`
       - `EXPOSE 8000`
       - `HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]`
       - `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`
    3. Create `docker-compose.yml` defining `backend` and `frontend` services and named volume `village_data`:
       - `backend`: `build: { context: ., dockerfile: backend/Dockerfile }`, `ports: ["8000:8000"]`, directory mounts `village_data:/app/data` and `./logs:/app/logs`, and environment variables using `${VAR:-default}` syntax (`APP_ENV`, `SIM_TICK_SECONDS`, `SIM_SPEED`, `SIM_SEED`, `SIM_AUTO_START`, `MAP_PATH: /app/assets/map.json`, `CORS_ORIGINS`, `LLM_PROVIDER: ${LLM_PROVIDER:-mock}`, `DATABASE_URL: sqlite+aiosqlite:////app/data/ai_village.db`, `REPLAY_LOG_DIR: /app/logs`, `EMBEDDING_PROVIDER: ${EMBEDDING_PROVIDER:-auto}`, `GEMINI_API_KEY: ${GEMINI_API_KEY:-}`, `GEMINI_ROUTINE_MODEL`, `GEMINI_PLANNING_MODEL`, `LLM_DAILY_BUDGET_USD`, `LLM_DAILY_TOKEN_LIMIT`, `LLM_MAX_RETRIES`, `RETRIEVAL_*`, `REFLECTION_THRESHOLD`), plus `healthcheck` hitting `http://127.0.0.1:8000/health` via Python `urllib.request`.
       - `frontend`: `build: { context: ., dockerfile: frontend/Dockerfile }`, `ports: ["5173:80"]`, `depends_on: { backend: { condition: service_healthy } }`.

    AVOID: Using `MAP_JSON_PATH` because `Settings` (`backend/app/config.py:27`) defines `map_path` (`MAP_PATH`) with `extra="ignore"`.
    AVOID: Binding a single `.db` file in Docker volumes because SQLite WAL mode (`backend/app/db.py:54`) creates sibling `-wal` and `-shm` files inside `/app/data`.
    AVOID: Installing default PyPI `torch` without `--extra-index-url https://download.pytorch.org/whl/cpu` because it pulls multi-GB CUDA dependencies.
  </action>
  <verify>
    Verify `backend/Dockerfile`, `.dockerignore`, and `docker-compose.yml` exist and contain required keys using Python stdlib check from repo root:
    `backend/.venv/Scripts/python.exe -c "from pathlib import Path; b=Path('backend/Dockerfile').read_text(); c=Path('docker-compose.yml').read_text(); assert 'download.pytorch.org/whl/cpu' in b and 'MAP_PATH=/app/assets/map.json' in b and '/app/assets/map.json' in b; assert 'village_data:/app/data' in c and './logs:/app/logs' in c and '5173:80' in c and '8000:8000' in c; print('DOCKER_CONFIG_OK')"`
  </verify>
  <done>
    `.dockerignore`, `backend/Dockerfile`, and `docker-compose.yml` exist with CPU-only PyTorch, baked `/app/assets/map.json`, directory mounts `/app/data` and `/app/logs`, `/health` healthchecks, and default mock mode requiring no API key.
  </done>
</task>

<task type="auto">
  <name>Create frontend/nginx.conf and multi-stage frontend/Dockerfile</name>
  <files>
    frontend/nginx.conf
    frontend/Dockerfile
  </files>
  <action>
    Configure Nginx as the production static asset server and reverse proxy mirroring `frontend/vite.config.ts` so same-origin browser requests (`apiClient.ts` and `wsClient.ts`) work identically on `http://localhost:5173`.

    Steps:
    1. Create `frontend/nginx.conf` (mounted at `/etc/nginx/conf.d/default.conf`, which runs inside Nginx's `http {}` context):
       - Define WebSocket upgrade mapping:
         ```nginx
         map $http_upgrade $connection_upgrade {
             default upgrade;
             '' close;
         }
         ```
       - Configure `server { listen 80; server_name _; root /usr/share/nginx/html; index index.html; ... }`.
       - Proxy WebSocket `/ws`:
         ```nginx
         location = /ws {
             proxy_pass http://backend:8000;
             proxy_http_version 1.1;
             proxy_set_header Upgrade $http_upgrade;
             proxy_set_header Connection $connection_upgrade;
             proxy_set_header Host $host;
             proxy_set_header X-Real-IP $remote_addr;
             proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
             proxy_read_timeout 3600s;
             proxy_send_timeout 3600s;
         }
         ```
       - Proxy all 8 FastAPI REST prefixes (`/health`, `/world`, `/agents`, `/events`, `/sim`, `/relationships`, `/metrics`, `/replay`):
         ```nginx
         location ~ ^/(health|world|agents|events|sim|relationships|metrics|replay)(/|$) {
             proxy_pass http://backend:8000;
             proxy_http_version 1.1;
             proxy_set_header Host $host;
             proxy_set_header X-Real-IP $remote_addr;
             proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
             proxy_set_header X-Forwarded-Proto $scheme;
         }
         ```
       - Serve `/assets/` directly (`try_files $uri =404;`) so missing tileset/map assets fail fast instead of returning `index.html`, and serve SPA fallback `location / { try_files $uri $uri/ /index.html; }`.
    2. Create `frontend/Dockerfile` using multi-stage build from repo root context (`context: .`, `dockerfile: frontend/Dockerfile`, so root `.dockerignore` excludes `frontend/node_modules` and `frontend/dist`):
       - Stage 1 (`FROM node:20-alpine AS builder`): `WORKDIR /app`, `COPY frontend/package.json frontend/package-lock.json ./`, `RUN npm ci`, `COPY frontend/ ./`, `RUN npm run build`.
       - Stage 2 (`FROM nginx:1.27-alpine`): `COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf`, `COPY --from=builder /app/dist /usr/share/nginx/html`, `EXPOSE 80`, `CMD ["nginx", "-g", "daemon off;"]`.

    AVOID: Omitting `/world` from `frontend/nginx.conf` because `fetchWorld()` (`frontend/src/net/apiClient.ts:113`) calls `GET /world` at boot.
    AVOID: Leaving Nginx's default `proxy_read_timeout 60s` on `/ws` because `VillageWsClient` is passive and simulation pause periods exceed 60s.
    AVOID: Adding a trailing slash to `proxy_pass http://backend:8000;` inside regex `location ~ ...` because Nginx forbids a URI component on regex `proxy_pass`.
  </action>
  <verify>
    Verify `frontend/nginx.conf` and `frontend/Dockerfile` contain all 8 REST prefixes, `/ws` upgrade headers, `proxy_read_timeout 3600s`, and multi-stage `node:20-alpine` -> `nginx:1.27-alpine`:
    `backend/.venv/Scripts/python.exe -c "from pathlib import Path; n=Path('frontend/nginx.conf').read_text(); d=Path('frontend/Dockerfile').read_text(); assert all(p in n for p in ('health','world','agents','events','sim','relationships','metrics','replay','/ws','Upgrade','3600s')); assert 'node:20-alpine' in d and 'nginx:1.27-alpine' in d and 'npm ci' in d and 'npm run build' in d; print('FRONTEND_DOCKER_OK')"`
  </verify>
  <done>
    `frontend/nginx.conf` proxies `/ws` (with `Upgrade` + `3600s` timeout) and all 8 FastAPI REST prefixes to `http://backend:8000`, and `frontend/Dockerfile` builds Vite `dist/` on `node:20-alpine` into `nginx:1.27-alpine`.
  </done>
</task>

<task type="auto">
  <name>Add Docker/Nginx route-parity contract test and CI Compose validation</name>
  <files>
    backend/tests/test_docker_packaging.py
    .github/workflows/ci.yml
  </files>
  <action>
    Create offline automated tests enforcing container/proxy/settings invariants and add `docker compose config --quiet` validation to GitHub Actions CI.

    Steps:
    1. Create `backend/tests/test_docker_packaging.py` using ONLY Python stdlib + `app.main.create_app` + `app.config.Settings` + `fastapi.routing.APIRoute` + `starlette.routing.WebSocketRoute` (no `pyyaml` dependency since `pyyaml` is not in `backend/pyproject.toml`!):
       - Assert `.dockerignore`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, and `docker-compose.yml` exist and are non-empty, and verify `.dockerignore` excludes `node_modules`/`.venv`/`.env`/`*.db` without ignoring `backend/`, `frontend/`, or `frontend/public/assets/map.json`.
       - Inspect `create_app(Settings(sim_auto_start=False)).routes` dynamically to collect every non-docs REST route root prefix (excluding `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`) and every WebSocket route path (`/ws`), and assert `frontend/nginx.conf` explicitly matches EVERY single REST prefix (`health`, `world`, `agents`, `events`, `sim`, `relationships`, `metrics`, `replay`) plus `/ws` with `Upgrade`, `Connection`, and `proxy_read_timeout 3600s`.
       - Assert `backend/Dockerfile` uses `python:3.12-slim`, `--extra-index-url https://download.pytorch.org/whl/cpu`, copies `frontend/public/assets/map.json` to `/app/assets/map.json`, sets `MAP_PATH=/app/assets/map.json`, `DATABASE_URL=sqlite+aiosqlite:////app/data/ai_village.db`, `REPLAY_LOG_DIR=/app/logs`, exposes `8000`, and defines a `/health` `HEALTHCHECK`.
       - Assert `frontend/Dockerfile` uses `node:20-alpine` and `nginx:1.27-alpine`, copies `frontend/nginx.conf` to `/etc/nginx/conf.d/default.conf`, and exposes `80`.
       - Assert `docker-compose.yml` defines `backend` and `frontend`, maps `8000:8000` and `5173:80`, mounts `/app/data` (and does NOT mount a single `.db` file), mounts `./logs:/app/logs`, sets `MAP_PATH`, `DATABASE_URL`, `REPLAY_LOG_DIR`, `LLM_PROVIDER`, and makes `frontend` depend on `backend` (`service_healthy`).
    2. Edit `.github/workflows/ci.yml` to add a `docker-compose` job (`runs-on: ubuntu-latest`, `timeout-minutes: 5`) that checks out the repository and runs `docker compose config --quiet` (validating `docker-compose.yml` schema and variable interpolation in CI on every push/PR without touching existing `backend` or `frontend` jobs).

    AVOID: Importing `yaml` (`PyYAML`) in `backend/tests/test_docker_packaging.py` because `pyyaml` is not declared in `backend/pyproject.toml`.
    AVOID: Modifying existing `backend` or `frontend` CI jobs in `.github/workflows/ci.yml` beyond adding the new Compose validation job.
  </action>
  <verify>
    Run each command individually (never chain with `&&`):
    - `backend/.venv/Scripts/ruff.exe check backend/tests/test_docker_packaging.py`
    - `backend/.venv/Scripts/mypy.exe --config-file backend/pyproject.toml backend/tests/test_docker_packaging.py`
    - From `backend/` working directory: `.venv/Scripts/pytest.exe -v tests/test_docker_packaging.py`
  </verify>
  <done>
    `backend/tests/test_docker_packaging.py` passes offline with 0 warnings/errors, `ruff` and `mypy` pass cleanly, and `.github/workflows/ci.yml` validates `docker compose config --quiet`.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] `.dockerignore`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, and `docker-compose.yml` exist and pass all contract checks in `backend/tests/test_docker_packaging.py`
- [ ] `frontend/nginx.conf` matches 100% of FastAPI REST prefixes (`/health`, `/world`, `/agents`, `/events`, `/sim`, `/relationships`, `/metrics`, `/replay`) and `/ws` with `Upgrade` + `proxy_read_timeout 3600s`
- [ ] `.github/workflows/ci.yml` validates `docker compose config --quiet` on `ubuntu-latest`

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in existing backend tests, `ruff`, or `mypy`
