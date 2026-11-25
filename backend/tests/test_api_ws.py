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
                assert frame_type in {"tick", "dialogue", "event", "reflection"}
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


def test_sim_control_agent_detail_and_relationships_endpoints(tmp_path: Path) -> None:
    db_path = tmp_path / "test_api_phase4.db"
    app = create_app(
        Settings(
            sim_auto_start=False,
            sim_tick_seconds=0.05,
            database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        )
    )

    with TestClient(app) as client:
        for invalid_speed in (2, 0, True, False, "4"):
            bad_resp = client.post("/sim/speed", json={"speed": invalid_speed})
            assert bad_resp.status_code == 422

        speed_resp = client.post("/sim/speed", json={"speed": 4})
        assert speed_resp.status_code == 200
        speed_data = speed_resp.json()
        assert {"running", "speed", "tick", "sim_time", "day"} <= set(speed_data.keys())
        assert speed_data["speed"] == 4
        assert speed_data["running"] is False
        assert speed_data["day"] >= 1

        start_resp = client.post("/sim/start")
        assert start_resp.status_code == 200
        start_data = start_resp.json()
        assert start_data["running"] is True
        assert start_data["speed"] == 4

        pause_resp = client.post("/sim/pause")
        assert pause_resp.status_code == 200
        pause_data = pause_resp.json()
        assert pause_data["running"] is False
        assert pause_data["speed"] == 4

        unknown_resp = client.get("/agents/unknown_id")
        assert unknown_resp.status_code == 404

        maya_resp = client.get("/agents/maya")
        assert maya_resp.status_code == 200
        maya = maya_resp.json()
        assert maya["id"] == "maya"
        assert maya["name"] == "Maya"
        assert maya["role"] == "Baker"
        assert maya["home_location"] == "Home_Maya"
        assert maya["current_location"] == "Home_Maya"
        assert maya["mood"] == "calm"
        assert maya["accumulated_importance"] >= 0
        assert maya["reflection_threshold"] == 150

        persona = maya["persona"]
        assert persona["id"] == "maya"
        assert persona["home_location"] == "Home_Maya"
        assert len(persona["traits"]) >= 3
        assert len(persona["starting_goals"]) >= 2

        plan = maya["plan"]
        assert set(plan.keys()) == {
            "day",
            "active_block_index",
            "active_minute_index",
            "hourly_focus",
            "current_step",
            "daily_plan",
        }
        assert len(plan["daily_plan"]) >= 3

        assert len(maya["recent_memories"]) >= 2
        assert len(maya["top_memories"]) >= 1
        assert isinstance(maya["reflections"], list)
        assert isinstance(maya["relationships"], list)

        for mem in maya["recent_memories"] + maya["top_memories"] + maya["reflections"]:
            assert "embedding" not in mem
            assert {
                "id",
                "type",
                "text",
                "importance",
                "created_tick",
                "last_access_tick",
                "cited_memory_ids",
            } <= set(mem.keys())

        rel_resp = client.get("/relationships")
        assert rel_resp.status_code == 200
        rel_data = rel_resp.json()
        assert len(rel_data["nodes"]) == 8
        assert {node["id"] for node in rel_data["nodes"]} == {
            "maya",
            "liam",
            "elena",
            "noah",
            "clara",
            "marcus",
            "aria",
            "sam",
        }
        for node in rel_data["nodes"]:
            assert {"id", "name", "role", "mood"} <= set(node.keys())
        assert isinstance(rel_data["edges"], list)
