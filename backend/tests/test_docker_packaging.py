"""Offline structural and route-parity contract tests for Docker and Nginx packaging."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Iterator

from fastapi.routing import APIRoute
from starlette.routing import WebSocketRoute

from app.config import REPO_ROOT, Settings
from app.main import create_app

DOCS_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
EXPECTED_REST_PREFIXES = {
    "health",
    "world",
    "agents",
    "events",
    "sim",
    "relationships",
    "metrics",
    "replay",
}


def _read_repo_file(relative_path: str) -> str:
    path = REPO_ROOT / relative_path
    assert path.is_file(), f"Missing required packaging artifact: {relative_path}"
    content = path.read_text(encoding="utf-8")
    assert content.strip(), f"Packaging artifact is empty: {relative_path}"
    return content


def test_required_packaging_files_and_dockerignore() -> None:
    """Verify all Docker/Compose/Nginx artifacts exist and .dockerignore preserves assets."""
    dockerignore_text = _read_repo_file(".dockerignore")
    _read_repo_file("backend/Dockerfile")
    _read_repo_file("frontend/Dockerfile")
    _read_repo_file("frontend/nginx.conf")
    _read_repo_file("docker-compose.yml")

    assert (REPO_ROOT / "frontend" / "public" / "assets" / "map.json").is_file()

    patterns = [
        line.strip()
        for line in dockerignore_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    joined = "\n".join(patterns)
    assert "node_modules" in joined
    assert ".venv" in joined
    assert ".env" in joined
    assert "*.db" in joined

    required_paths = [
        "backend/app/main.py",
        "backend/pyproject.toml",
        "frontend/package.json",
        "frontend/public/assets/map.json",
        ".env.example",
    ]
    for rel_path in required_paths:
        assert not any(
            fnmatch.fnmatch(rel_path, pattern)
            or fnmatch.fnmatch(rel_path.split("/")[0], pattern)
            for pattern in patterns
            if not pattern.startswith("!")
        ), f".dockerignore unexpectedly excludes {rel_path}"


def _iter_app_routes(routes: Iterable[object], prefix: str = "") -> Iterator[tuple[str, object]]:
    """Yield (full_path, route) pairs across FastAPI routers and flat route lists."""
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None and hasattr(original_router, "routes"):
            include_context = getattr(route, "include_context", None)
            sub_prefix = str(getattr(include_context, "prefix", "") or "")
            yield from _iter_app_routes(original_router.routes, prefix=f"{prefix}{sub_prefix}")
            continue
        nested_routes = getattr(route, "routes", None)
        if nested_routes is not None:
            mount_path = str(getattr(route, "path", "") or "")
            yield from _iter_app_routes(nested_routes, prefix=f"{prefix}{mount_path}")
            continue
        route_path = str(getattr(route, "path", "") or "")
        yield f"{prefix}{route_path}", route


def test_nginx_proxies_every_fastapi_rest_and_websocket_route() -> None:
    """Enforce 100% route parity between FastAPI create_app() and frontend/nginx.conf."""
    app = create_app(Settings(sim_auto_start=False))

    discovered_rest_prefixes: set[str] = set()
    discovered_ws_paths: set[str] = set()

    for full_path, route in _iter_app_routes(app.routes):
        if isinstance(route, APIRoute):
            if full_path in DOCS_PATHS:
                continue
            prefix = full_path.lstrip("/").split("/", 1)[0]
            assert prefix, f"Unexpected root REST route without prefix: {full_path!r}"
            discovered_rest_prefixes.add(prefix)
        elif isinstance(route, WebSocketRoute):
            discovered_ws_paths.add(full_path)

    assert discovered_rest_prefixes == EXPECTED_REST_PREFIXES
    assert discovered_ws_paths == {"/ws"}

    nginx_conf = _read_repo_file("frontend/nginx.conf")

    assert "map $http_upgrade $connection_upgrade" in nginx_conf
    assert "default upgrade;" in nginx_conf
    assert "'' close;" in nginx_conf

    ws_match = re.search(
        r"location\s+(?:=\s+)?/ws\s*\{(?P<body>[^}]*)\}",
        nginx_conf,
        flags=re.DOTALL,
    )
    assert ws_match is not None, "frontend/nginx.conf is missing a /ws location block"
    ws_body = ws_match.group("body")
    assert "proxy_pass http://backend:8000;" in ws_body
    assert "proxy_http_version 1.1;" in ws_body
    assert "proxy_set_header Upgrade $http_upgrade;" in ws_body
    assert "proxy_set_header Connection $connection_upgrade;" in ws_body
    assert "proxy_read_timeout 3600s;" in ws_body
    assert "proxy_send_timeout 3600s;" in ws_body

    rest_match = re.search(
        r"location\s+~\s+\^/\((?P<prefixes>[^)]+)\)\(/\|\$\)\s*\{(?P<body>[^}]*)\}",
        nginx_conf,
        flags=re.DOTALL,
    )
    assert rest_match is not None, (
        "frontend/nginx.conf must proxy all FastAPI REST prefixes via "
        "'location ~ ^/(...)(/|$)'"
    )
    proxied_prefixes = set(rest_match.group("prefixes").split("|"))
    assert proxied_prefixes == discovered_rest_prefixes

    rest_body = rest_match.group("body")
    assert "proxy_pass http://backend:8000;" in rest_body
    assert "proxy_pass http://backend:8000/;" not in rest_body

    assert re.search(
        r"location\s+/assets/\s*\{[^}]*try_files\s+\$uri\s+=404;",
        nginx_conf,
        flags=re.DOTALL,
    )
    assert re.search(
        r"location\s+/\s*\{[^}]*try_files\s+\$uri\s+\$uri/\s+/index\.html;",
        nginx_conf,
        flags=re.DOTALL,
    )


def test_backend_and_frontend_dockerfiles() -> None:
    """Validate backend CPU-PyTorch Dockerfile and multi-stage frontend Dockerfile."""
    backend_df = _read_repo_file("backend/Dockerfile")
    assert "FROM python:3.12-slim" in backend_df
    assert "--extra-index-url https://download.pytorch.org/whl/cpu" in backend_df
    assert "COPY frontend/public/assets/map.json /app/assets/map.json" in backend_df
    assert "mkdir -p /app/data /app/logs" in backend_df
    assert "MAP_PATH=/app/assets/map.json" in backend_df
    assert "MAP_JSON_PATH" not in backend_df
    assert "DATABASE_URL=sqlite+aiosqlite:////app/data/ai_village.db" in backend_df
    assert "REPLAY_LOG_DIR=/app/logs" in backend_df
    assert "LLM_PROVIDER=mock" in backend_df
    assert "EMBEDDING_PROVIDER=auto" in backend_df
    assert "EXPOSE 8000" in backend_df
    assert "HEALTHCHECK" in backend_df
    assert "http://127.0.0.1:8000/health" in backend_df
    assert 'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]' in backend_df

    for env_key in (
        "MAP_PATH",
        "DATABASE_URL",
        "REPLAY_LOG_DIR",
        "LLM_PROVIDER",
        "EMBEDDING_PROVIDER",
    ):
        assert env_key.lower() in Settings.model_fields

    frontend_df = _read_repo_file("frontend/Dockerfile")
    assert "FROM node:20-alpine AS builder" in frontend_df
    assert "COPY frontend/package.json frontend/package-lock.json ./" in frontend_df
    assert "RUN npm ci" in frontend_df
    assert "COPY frontend/ ./" in frontend_df
    assert "RUN npm run build" in frontend_df
    assert "FROM nginx:1.27-alpine" in frontend_df
    assert "COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf" in frontend_df
    assert "COPY --from=builder /app/dist /usr/share/nginx/html" in frontend_df
    assert "EXPOSE 80" in frontend_df


def test_docker_compose_wiring_and_settings_parity() -> None:
    """Validate docker-compose.yml services, directory volumes, healthcheck, and Settings keys."""
    compose_text = _read_repo_file("docker-compose.yml")

    assert re.search(r"^services:\s*$", compose_text, flags=re.MULTILINE)
    assert re.search(r"^  backend:\s*$", compose_text, flags=re.MULTILINE)
    assert re.search(r"^  frontend:\s*$", compose_text, flags=re.MULTILINE)
    assert re.search(r"^volumes:\s*$", compose_text, flags=re.MULTILINE)
    assert re.search(r"^  village_data:\s*$", compose_text, flags=re.MULTILINE)

    assert "dockerfile: backend/Dockerfile" in compose_text
    assert "dockerfile: frontend/Dockerfile" in compose_text
    assert '"8000:8000"' in compose_text
    assert '"5173:80"' in compose_text

    # SQLite WAL requires directory mounts rather than single-file .db bind mounts.
    assert "village_data:/app/data" in compose_text
    assert "./logs:/app/logs" in compose_text
    assert not re.search(r"\.(db|sqlite)\s*:/", compose_text)

    assert "MAP_PATH: /app/assets/map.json" in compose_text
    assert "MAP_JSON_PATH" not in compose_text
    assert "DATABASE_URL: sqlite+aiosqlite:////app/data/ai_village.db" in compose_text
    assert "REPLAY_LOG_DIR: /app/logs" in compose_text
    assert "LLM_PROVIDER: ${LLM_PROVIDER:-mock}" in compose_text
    assert "http://127.0.0.1:8000/health" in compose_text
    assert "condition: service_healthy" in compose_text

    env_block_match = re.search(
        r"    environment:\n(?P<block>(?:      [A-Z0-9_]+:.*\n)+)",
        compose_text,
    )
    assert env_block_match is not None, "Missing backend environment block in docker-compose.yml"
    env_keys = re.findall(r"^\s+([A-Z0-9_]+):", env_block_match.group("block"), flags=re.MULTILINE)
    assert len(env_keys) >= 20
    for key in env_keys:
        assert key.lower() in Settings.model_fields, (
            f"Environment variable {key} in docker-compose.yml does not match Settings"
        )
