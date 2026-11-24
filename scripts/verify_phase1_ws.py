"""Phase 1 end-to-end verification script for built assets, REST endpoints, and /ws sync."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import websockets

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
HOST = "127.0.0.1"
PORT = 8011
BASE_HTTP_URL = f"http://{HOST}:{PORT}"
WS_URL = f"ws://{HOST}:{PORT}/ws"
REQUIRED_LOCATIONS = {"Cafe", "Park", "Market", "Town Square"}


def verify_frontend_dist() -> None:
    """Assert that built frontend HTML and required Tiled/sprite assets exist."""
    required_files = [
        FRONTEND_DIST / "index.html",
        FRONTEND_DIST / "assets" / "map.json",
        FRONTEND_DIST / "assets" / "tileset.png",
        FRONTEND_DIST / "assets" / "sprites.png",
    ]
    missing = [
        str(path)
        for path in required_files
        if not path.is_file() or path.stat().st_size == 0
    ]
    if missing:
        raise FileNotFoundError(
            f"Missing or empty frontend build artifact(s): {', '.join(missing)}"
        )


def _read_process_output(proc: subprocess.Popen[bytes]) -> str:
    if proc.stdout is None:
        return ""
    return proc.stdout.read().decode("utf-8", errors="replace")


async def _wait_for_health(
    client: httpx.AsyncClient,
    proc: subprocess.Popen[bytes],
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: str = "no response"

    while time.monotonic() < deadline:
        exit_code = proc.poll()
        if exit_code is not None:
            output = _read_process_output(proc)
            raise RuntimeError(
                f"Uvicorn exited early with status {exit_code}. Output:\n{output}"
            )
        try:
            response = await client.get("/health")
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        await asyncio.sleep(0.15)

    raise TimeoutError(
        f"Server at {BASE_HTTP_URL}/health did not become ready within {timeout_seconds}s "
        f"(last error: {last_error})"
    )


async def verify_live_server(proc: subprocess.Popen[bytes]) -> tuple[list[int], int]:
    """Verify /health, /world, /agents, and 6 live WebSocket /ws ticks."""
    async with httpx.AsyncClient(base_url=BASE_HTTP_URL, timeout=3.0) as client:
        await _wait_for_health(client, proc, timeout_seconds=10.0)

        world_resp = await client.get("/world")
        if world_resp.status_code != 200:
            raise RuntimeError(f"GET /world returned HTTP {world_resp.status_code}")
        world_data = world_resp.json()
        locations = world_data.get("locations", [])
        if not isinstance(locations, list) or len(locations) < 10:
            raise AssertionError(
                f"Expected >= 10 named locations in /world, got {len(locations)}"
            )

        location_names = {
            str(loc.get("name", "")) for loc in locations if isinstance(loc, dict)
        }
        missing_core = REQUIRED_LOCATIONS - location_names
        if missing_core:
            raise AssertionError(f"/world missing expected locations: {sorted(missing_core)}")
        if not any(name.startswith("Home_") for name in location_names):
            raise AssertionError("/world missing any 'Home_*' location")

        agents_resp = await client.get("/agents")
        if agents_resp.status_code != 200:
            raise RuntimeError(f"GET /agents returned HTTP {agents_resp.status_code}")
        agents_data = agents_resp.json()
        if not isinstance(agents_data, list) or len(agents_data) != 8:
            raise AssertionError(
                f"Expected 8 seeded agents from GET /agents, got {len(agents_data)}"
            )

    observed_ticks: list[int] = []
    positions_by_agent: dict[str, set[tuple[int, int]]] = {}

    async with websockets.connect(WS_URL, open_timeout=5.0) as ws:
        for _ in range(6):
            raw_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            payload = json.loads(raw_msg)
            if not isinstance(payload, dict) or payload.get("type") != "tick":
                raise AssertionError(f"Unexpected /ws message payload: {payload!r}")

            tick = payload.get("tick")
            if not isinstance(tick, int) or isinstance(tick, bool):
                raise AssertionError(f"Invalid tick value in /ws message: {tick!r}")
            if observed_ticks and tick <= observed_ticks[-1]:
                raise AssertionError(
                    f"Non-monotonic tick sequence: {observed_ticks + [tick]}"
                )
            observed_ticks.append(tick)

            agents = payload.get("agents")
            if not isinstance(agents, list) or len(agents) != 8:
                raise AssertionError(f"Expected 8 agents per tick, got {agents!r}")

            coords_seen: set[tuple[int, int]] = set()
            for agent in agents:
                if not isinstance(agent, dict):
                    raise AssertionError(f"Invalid agent entry: {agent!r}")
                agent_id = str(agent["id"])
                coord = (int(agent["x"]), int(agent["y"]))
                if coord in coords_seen:
                    raise AssertionError(
                        f"Duplicate agent coordinate {coord} at tick {tick}: {agents!r}"
                    )
                coords_seen.add(coord)
                positions_by_agent.setdefault(agent_id, set()).add(coord)

    moved_agents = sum(1 for history in positions_by_agent.values() if len(history) > 1)
    if moved_agents < 3:
        raise AssertionError(
            f"Expected at least 3 agents to move across 6 ticks, got {moved_agents} "
            f"(positions={positions_by_agent!r})"
        )

    return observed_ticks, moved_agents


def main() -> int:
    """Run all Phase 1 end-to-end verification checks and print summary."""
    verify_frontend_dist()

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "verify_phase1_ws.db"
        env = os.environ.copy()
        env["SIM_TICK_SECONDS"] = "0.1"
        env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                HOST,
                "--port",
                str(PORT),
            ],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        try:
            observed_ticks, moved_agents = asyncio.run(verify_live_server(proc))
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            if proc.stdout is not None:
                proc.stdout.close()

    print(
        f"e2e_ws_ok ticks={observed_ticks} moved_agents={moved_agents}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
