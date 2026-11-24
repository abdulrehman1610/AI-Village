"""Offline integration tests for REST endpoints and WebSocket /ws live broadcasts."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

EXPECTED_LOCATION_NAMES = {
    "Cafe",
    "Park",
    "Market",
    "Town Square",
    "Bakery",
    "Library",
    "Home_Maya",
    "Home_Liam",
    "Home_Elena",
    "Home_Noah",
}


def test_rest_endpoints_and_initial_websocket_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "test_api_snapshot.db"
    app = create_app(
        Settings(
            sim_auto_start=False,
            sim_tick_seconds=0.05,
            database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        )
    )

    with TestClient(app) as client:
        assert app.state.db is not None
        assert app.state.embedding_service is not None
        assert app.state.memory_store is not None
        assert app.state.memory_retriever is not None
        assert app.state.llm_gateway is not None

        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        assert health_data["status"] == "ok"
        assert health_data["agents"] == 8
        assert health_data["map_width"] == 40
        assert health_data["map_height"] == 30
        assert health_data["tick"] == 0

        world_resp = client.get("/world")
        assert world_resp.status_code == 200
        world_data = world_resp.json()
        assert world_data["width"] == 40
        assert world_data["height"] == 30
        assert world_data["tile_size"] == 32
        location_names = {loc["name"] for loc in world_data["locations"]}
        assert location_names == EXPECTED_LOCATION_NAMES

        agents_resp = client.get("/agents")
        assert agents_resp.status_code == 200
        agents_data = agents_resp.json()
        assert len(agents_data) == 8
        assert {agent["sprite_index"] for agent in agents_data} == set(range(8))
        for agent in agents_data:
            assert {"id", "name", "role", "sprite_index", "x", "y", "current_action"} <= set(
                agent.keys()
            )

        with client.websocket_connect("/ws") as ws:
            initial_msg = ws.receive_json()
            assert initial_msg["type"] == "tick"
            assert initial_msg["tick"] == 0
            assert len(initial_msg["agents"]) == 8

    with closing(sqlite3.connect(str(db_path))) as conn:
        agent_count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        memory_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        sim_tick = conn.execute("SELECT tick FROM sim_state WHERE id = 1").fetchone()[0]
        assert agent_count == 8
        assert memory_count >= 16
        assert sim_tick == 0


def test_websocket_streams_advancing_ticks_and_moving_agents(tmp_path: Path) -> None:
    db_path = tmp_path / "test_api_ws.db"
    app = create_app(
        Settings(
            sim_auto_start=True,
            sim_tick_seconds=0.05,
            database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        )
    )

    with TestClient(app) as client:
        assert app.state.db is not None
        assert app.state.memory_store is not None
        assert app.state.memory_retriever is not None
        assert app.state.llm_gateway is not None

        with client.websocket_connect("/ws") as ws:
            ticks: list[dict[str, Any]] = []
            for _ in range(25):
                frame = ws.receive_json()
                frame_type = frame.get("type")
                assert frame_type in {"tick", "dialogue", "event"}
                if frame_type == "tick":
                    ticks.append(frame)
                    if len(ticks) == 2:
                        break
            assert len(ticks) == 2
            msg1, msg2 = ticks
            assert msg1["type"] == "tick"
            assert msg2["type"] == "tick"
            assert msg2["tick"] > msg1["tick"]
            assert len(msg1["agents"]) == 8
            assert len(msg2["agents"]) == 8

            coords1 = {(a["id"], a["x"], a["y"]) for a in msg1["agents"]}
            coords2 = {(a["id"], a["x"], a["y"]) for a in msg2["agents"]}
            assert coords1 != coords2

    with closing(sqlite3.connect(str(db_path))) as conn:
        agent_count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        sim_tick = conn.execute("SELECT tick FROM sim_state WHERE id = 1").fetchone()[0]
        assert agent_count == 8
        assert sim_tick >= msg2["tick"]
        assert sim_tick > 0
