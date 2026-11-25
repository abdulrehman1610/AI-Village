"""Offline integration tests for REST endpoints and WebSocket /ws live broadcasts."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from sim.engine import SimulationEngine

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
            replay_log_dir=str(tmp_path / "logs"),
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
            replay_log_dir=str(tmp_path / "logs"),
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
                assert frame_type in {"tick", "dialogue", "event", "reflection", "metrics"}
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
            replay_log_dir=str(tmp_path / "logs"),
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


def test_metrics_and_replay_endpoints_and_ws_metrics(tmp_path: Path) -> None:
    db_path = tmp_path / "test_api_metrics_replay.db"
    replay_dir = tmp_path / "logs"
    app = create_app(
        Settings(
            sim_auto_start=False,
            sim_tick_seconds=0.05,
            database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
            replay_log_dir=str(replay_dir),
        )
    )

    with TestClient(app) as client:
        assert app.state.replay_logger is not None
        assert client.portal is not None

        initial_metrics_resp = client.get("/metrics")
        assert initial_metrics_resp.status_code == 200
        initial_metrics = initial_metrics_resp.json()
        assert {
            "tick",
            "sim_time",
            "day",
            "total_calls",
            "cache_hits",
            "cache_hit_rate",
            "tokens_in",
            "tokens_out",
            "total_tokens",
            "cost_est",
            "avg_latency_ms",
            "max_latency_ms",
            "daily_budget_usd",
            "daily_token_limit",
            "budget_day",
            "budget_tokens_used",
            "budget_cost_used",
            "by_purpose",
            "by_model",
            "history",
        } <= set(initial_metrics.keys())
        assert initial_metrics["tick"] == 0
        assert initial_metrics["day"] == 1
        assert initial_metrics["sim_time"] == "Day 1 06:00"
        assert initial_metrics["total_calls"] == 0
        assert initial_metrics["by_purpose"] == []
        assert initial_metrics["by_model"] == []
        assert initial_metrics["history"] == []

        initial_replay_resp = client.get("/replay")
        assert initial_replay_resp.status_code == 200
        initial_replay = initial_replay_resp.json()
        assert initial_replay["current_day"] == 1
        assert len(initial_replay["days"]) == 1
        day1_summary = initial_replay["days"][0]
        assert day1_summary["day"] == 1
        assert day1_summary["tick_count"] == 1
        assert day1_summary["first_tick"] == 0
        assert day1_summary["last_tick"] == 0

        day1_log_resp = client.get("/replay/1")
        assert day1_log_resp.status_code == 200
        day1_log = day1_log_resp.json()
        assert day1_log["day"] == 1
        assert day1_log["tick_count"] == 1
        assert day1_log["first_tick"] == 0
        assert day1_log["last_tick"] == 0
        assert len(day1_log["frames"]) == 1
        assert day1_log["frames"][0]["type"] == "tick"
        assert day1_log["frames"][0]["tick"] == 0

        assert client.get("/replay/99").status_code == 404
        assert client.get("/replay/0").status_code == 422

        # Playback controls must not append duplicate tick-0 snapshots into replay logs.
        assert client.post("/sim/speed", json={"speed": 4}).status_code == 200
        assert client.get("/replay/1").json()["tick_count"] == 1

        engine: SimulationEngine = app.state.engine

        with client.websocket_connect("/ws") as ws:
            initial_ws = ws.receive_json()
            assert initial_ws["type"] == "tick"
            assert initial_ws["tick"] == 0

            step1 = client.portal.call(engine.step_once)
            assert step1.tick == 1
            step2 = client.portal.call(engine.step_once)
            assert step2.tick == 2

            event_resp = client.post(
                "/events",
                json={"text": "Town bell rang at dawn", "location": "Town Square"},
            )
            assert event_resp.status_code == 200
            event_data = event_resp.json()
            event_id = event_data["id"]

            ws_frames: list[dict[str, Any]] = []
            seen_event = False
            for _ in range(80):
                frame = ws.receive_json()
                frame_type = frame.get("type")
                assert frame_type in {"tick", "dialogue", "event", "reflection", "metrics"}
                ws_frames.append(frame)
                if frame_type == "event" and frame.get("id") == event_id:
                    seen_event = True
                    break

            assert seen_event is True
            ws_ticks = [f["tick"] for f in ws_frames if f.get("type") == "tick"]
            assert ws_ticks == [1, 2]

            ws_metrics_frames = [f for f in ws_frames if f.get("type") == "metrics"]
            assert len(ws_metrics_frames) >= 1
            latest_ws_metrics = ws_metrics_frames[-1]
            assert latest_ws_metrics["total_calls"] > 0
            assert latest_ws_metrics["tokens_in"] > 0
            assert latest_ws_metrics["tokens_out"] > 0
            assert (
                latest_ws_metrics["total_tokens"]
                == latest_ws_metrics["tokens_in"] + latest_ws_metrics["tokens_out"]
            )
            assert len(latest_ws_metrics["by_purpose"]) >= 1
            assert len(latest_ws_metrics["by_model"]) >= 1
            assert len(latest_ws_metrics["history"]) >= 1

        final_metrics_resp = client.get("/metrics")
        assert final_metrics_resp.status_code == 200
        final_metrics = final_metrics_resp.json()
        assert final_metrics["tick"] == 2
        assert final_metrics["day"] == 1

        with closing(sqlite3.connect(str(db_path))) as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(tokens_in), 0), COALESCE(SUM(tokens_out), 0) "
                "FROM llm_calls"
            ).fetchone()
            db_calls, db_tokens_in, db_tokens_out = int(row[0]), int(row[1]), int(row[2])

        assert final_metrics["total_calls"] == db_calls
        assert final_metrics["tokens_in"] == db_tokens_in
        assert final_metrics["tokens_out"] == db_tokens_out
        assert final_metrics["total_tokens"] == db_tokens_in + db_tokens_out

        final_replay_resp = client.get("/replay")
        assert final_replay_resp.status_code == 200
        final_replay = final_replay_resp.json()
        assert final_replay["current_day"] == 1
        assert len(final_replay["days"]) == 1
        assert final_replay["days"][0]["tick_count"] == 3
        assert final_replay["days"][0]["first_tick"] == 0
        assert final_replay["days"][0]["last_tick"] == 2

        final_day1_resp = client.get("/replay/1")
        assert final_day1_resp.status_code == 200
        final_day1 = final_day1_resp.json()
        assert final_day1["tick_count"] == 3
        assert final_day1["first_tick"] == 0
        assert final_day1["last_tick"] == 2

        frames = final_day1["frames"]
        assert all(
            f.get("type") in {"tick", "dialogue", "event", "reflection"} for f in frames
        )
        assert [f["tick"] for f in frames if f.get("type") == "tick"] == [0, 1, 2]
        frame_ticks = [f["tick"] for f in frames]
        assert frame_ticks == sorted(frame_ticks)
        assert any(
            f.get("type") == "event"
            and f.get("id") == event_id
            and f.get("text") == "Town bell rang at dawn"
            for f in frames
        )
