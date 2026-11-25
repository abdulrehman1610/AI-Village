"""Offline Phase 4 integration tests: reflection, relationships, inspector, and time controls."""

from __future__ import annotations

import functools
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from sim.engine import SimulationEngine
from sim.world import WorldMap


def _move_other_agents_away(
    world: WorldMap,
    engine: SimulationEngine,
    keep_ids: set[str],
    safe_location: str = "Home_Noah",
) -> None:
    anchor = world.get_location(safe_location).anchor
    occupied = {
        (agent.x, agent.y)
        for agent_id, agent in engine.agents.items()
        if agent_id in keep_ids
    }
    for agent_id in sorted(engine.agents):
        if agent_id in keep_ids:
            continue
        agent = engine.agents[agent_id]
        spot = world.find_free_adjacent(anchor[0], anchor[1], occupied, max_radius=6)
        assert spot is not None, f"No free tile near {safe_location}"
        agent.x, agent.y = spot
        agent.path = []
        occupied.add(spot)


def test_threshold_150_reflection_cites_memories_and_emits_ws(tmp_path: Path) -> None:
    db_path = tmp_path / "phase4_reflection.db"
    app = create_app(
        Settings(
            sim_auto_start=False,
            sim_tick_seconds=0.05,
            database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
            replay_log_dir=str(tmp_path / "logs"),
        )
    )

    with TestClient(app) as client:
        assert client.portal is not None
        engine: SimulationEngine = app.state.engine
        assert engine.reflection_threshold == 150
        assert engine.brains["maya"].reflection_threshold == 150
        assert engine.brains["maya"].accumulated_importance == 0

        with client.websocket_connect("/ws") as ws:
            initial_tick = ws.receive_json()
            assert initial_tick["type"] == "tick"
            assert initial_tick["tick"] == 0

            # Inject 18 salient events near Home_Maya: 18 * 8 = 144 importance (< 150).
            for idx in range(18):
                ev = client.portal.call(
                    functools.partial(
                        engine.inject_event,
                        f"Harvest bulletin #{idx + 1}: fresh grain sacks delivered to Maya",
                        "Home_Maya",
                        radius=2,
                    )
                )
                assert "maya" in ev["affected_agents"]
                ws_event = ws.receive_json()
                assert ws_event["type"] == "event"

            assert engine.brains["maya"].accumulated_importance == 144
            assert engine.brains["maya"].should_reflect() is False

            # Stepping tick 1 generates Maya's daily plan (+6 importance -> 150 >= 150).
            tick1_payload = client.portal.call(engine.step_once)
            assert tick1_payload.tick == 1

            maya_detail_resp = client.get("/agents/maya")
            assert maya_detail_resp.status_code == 200
            maya_detail = maya_detail_resp.json()

            assert len(maya_detail["reflections"]) >= 1
            assert maya_detail["accumulated_importance"] < 150
            assert maya_detail["accumulated_importance"] == 0
            assert isinstance(maya_detail["mood"], str) and maya_detail["mood"].strip() != ""

            persisted_cited_sets: list[list[int]] = []
            for mem in maya_detail["reflections"]:
                assert "embedding" not in mem
                assert mem["type"] == "reflection"
                assert isinstance(mem["cited_memory_ids"], list)
                assert len(mem["cited_memory_ids"]) >= 1
                persisted_cited_sets.append(mem["cited_memory_ids"])

            # Receive tick 1 and all emitted reflection WS messages for Maya.
            tick1_seen = False
            maya_ws_reflections: list[dict[str, Any]] = []
            expected_reflection_count = len(maya_detail["reflections"])
            for _ in range(40):
                if tick1_seen and len(maya_ws_reflections) >= expected_reflection_count:
                    break
                frame = ws.receive_json()
                frame_type = frame.get("type")
                assert frame_type in {"tick", "dialogue", "event", "reflection", "metrics"}
                if frame_type == "tick" and frame.get("tick") == 1:
                    tick1_seen = True
                elif frame_type == "reflection" and frame.get("agent_id") == "maya":
                    maya_ws_reflections.append(frame)

            assert tick1_seen is True
            assert len(maya_ws_reflections) == expected_reflection_count
            for ws_ref in maya_ws_reflections:
                assert {
                    "type",
                    "tick",
                    "sim_time",
                    "agent_id",
                    "agent_name",
                    "insight",
                    "cited_memory_ids",
                } <= set(ws_ref.keys())
                assert ws_ref["type"] == "reflection"
                assert ws_ref["agent_id"] == "maya"
                assert ws_ref["agent_name"] == "Maya"
                assert isinstance(ws_ref["insight"], str) and ws_ref["insight"].strip()
                assert isinstance(ws_ref["cited_memory_ids"], list)
                assert len(ws_ref["cited_memory_ids"]) >= 1
                assert ws_ref["cited_memory_ids"] in persisted_cited_sets

            # Stepping 3 additional quiet ticks must not trigger a duplicate cascade reflection.
            duplicate_reflections: list[dict[str, Any]] = []
            for expected_tick in (2, 3, 4):
                payload = client.portal.call(engine.step_once)
                assert payload.tick == expected_tick
                for _ in range(30):
                    frame = ws.receive_json()
                    if frame.get("type") == "reflection" and frame.get("agent_id") == "maya":
                        duplicate_reflections.append(frame)
                    if frame.get("type") == "tick" and frame.get("tick") == expected_tick:
                        break

            assert duplicate_reflections == []
            after_quiet_resp = client.get("/agents/maya")
            assert after_quiet_resp.status_code == 200
            assert len(after_quiet_resp.json()["reflections"]) == expected_reflection_count


def test_conversation_relationship_and_mood_exposed_by_rest_apis(tmp_path: Path) -> None:
    db_path = tmp_path / "phase4_relationships.db"
    app = create_app(
        Settings(
            sim_auto_start=False,
            sim_tick_seconds=0.05,
            database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
            replay_log_dir=str(tmp_path / "logs"),
        )
    )

    with TestClient(app) as client:
        assert client.portal is not None
        engine: SimulationEngine = app.state.engine
        world: WorldMap = app.state.world

        # Generate initial Day 1 plans on tick 1 before pairing Maya and Liam.
        tick1_payload = client.portal.call(engine.step_once)
        assert tick1_payload.tick == 1

        maya = engine.agents["maya"]
        liam = engine.agents["liam"]
        _move_other_agents_away(world, engine, {"maya", "liam"}, safe_location="Home_Noah")

        occupied = {
            (agent.x, agent.y)
            for agent_id, agent in engine.agents.items()
            if agent_id != "liam"
        }
        adjacent = world.find_free_adjacent(maya.x, maya.y, occupied, max_radius=1)
        assert adjacent is not None
        liam.x, liam.y = adjacent
        liam.path = []

        # Inject a local event so both nearby agents deterministically initiate dialogue.
        ev = client.portal.call(
            functools.partial(
                engine.inject_event,
                "Morning sourdough & espresso tasting started at the corner",
                "Home_Maya",
                radius=4,
            )
        )
        assert set(ev["affected_agents"]) >= {"maya", "liam"}

        step_payload = client.portal.call(engine.step_once)
        assert step_payload.tick == 2

        rel_resp = client.get("/relationships")
        assert rel_resp.status_code == 200
        rel_data = rel_resp.json()
        assert len(rel_data["nodes"]) == 8

        pair_edges = [
            edge
            for edge in rel_data["edges"]
            if {edge["agent_a"], edge["agent_b"]} == {"liam", "maya"}
        ]
        assert len(pair_edges) == 1
        edge = pair_edges[0]
        assert edge["agent_a"] == "liam"
        assert edge["agent_b"] == "maya"
        assert edge["agent_a"] < edge["agent_b"]
        assert edge["agent_a_name"] == "Liam"
        assert edge["agent_b_name"] == "Maya"
        assert isinstance(edge["notes"], str) and edge["notes"].strip() != ""
        assert -1.0 <= edge["affinity"] <= 1.0

        maya_resp = client.get("/agents/maya")
        assert maya_resp.status_code == 200
        maya_detail = maya_resp.json()
        assert isinstance(maya_detail["mood"], str) and maya_detail["mood"].strip() != ""
        assert isinstance(maya_detail["current_action"], str) and maya_detail["current_action"]
        assert maya_detail["plan"]["day"] == 1
        assert len(maya_detail["plan"]["daily_plan"]) >= 5
        maya_liam_rels = [r for r in maya_detail["relationships"] if r["peer_id"] == "liam"]
        assert len(maya_liam_rels) == 1
        assert maya_liam_rels[0]["peer_name"] == "Liam"
        assert maya_liam_rels[0]["notes"] == edge["notes"]

        liam_resp = client.get("/agents/liam")
        assert liam_resp.status_code == 200
        liam_detail = liam_resp.json()
        assert isinstance(liam_detail["mood"], str) and liam_detail["mood"].strip() != ""
        assert isinstance(liam_detail["current_action"], str) and liam_detail["current_action"]
        assert liam_detail["plan"]["day"] == 1
        liam_maya_rels = [r for r in liam_detail["relationships"] if r["peer_id"] == "maya"]
        assert len(liam_maya_rels) == 1
        assert liam_maya_rels[0]["peer_name"] == "Maya"
        assert liam_maya_rels[0]["notes"] == edge["notes"]


def test_time_controls_rest_and_ws_live_sync(tmp_path: Path) -> None:
    db_path = tmp_path / "phase4_time_controls.db"
    app = create_app(
        Settings(
            sim_auto_start=True,
            sim_tick_seconds=0.4,
            database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
            replay_log_dir=str(tmp_path / "logs"),
        )
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            initial_frame = ws.receive_json()
            assert initial_frame["type"] == "tick"
            assert initial_frame["speed"] == 1

            pause_resp = client.post("/sim/pause")
            assert pause_resp.status_code == 200
            assert pause_resp.json()["running"] is False

            paused_ws_tick: dict[str, Any] | None = None
            for _ in range(25):
                frame = ws.receive_json()
                assert frame.get("type") in {"tick", "dialogue", "event", "reflection", "metrics"}
                if frame.get("type") == "tick" and frame.get("running") is False:
                    paused_ws_tick = frame
                    break
            assert paused_ws_tick is not None

            speed_resp = client.post("/sim/speed", json={"speed": 16})
            assert speed_resp.status_code == 200
            assert speed_resp.json()["speed"] == 16
            assert speed_resp.json()["running"] is False

            speed_ws_tick: dict[str, Any] | None = None
            for _ in range(25):
                frame = ws.receive_json()
                assert frame.get("type") in {"tick", "dialogue", "event", "reflection", "metrics"}
                if (
                    frame.get("type") == "tick"
                    and frame.get("speed") == 16
                    and frame.get("running") is False
                ):
                    speed_ws_tick = frame
                    break
            assert speed_ws_tick is not None

            start_t0 = time.monotonic()
            start_resp = client.post("/sim/start")
            assert start_resp.status_code == 200
            start_data = start_resp.json()
            assert start_data["running"] is True
            assert start_data["speed"] == 16
            baseline_tick = start_data["tick"]

            advancing_ticks: list[int] = []
            for _ in range(40):
                frame = ws.receive_json()
                assert frame.get("type") in {"tick", "dialogue", "event", "reflection", "metrics"}
                if (
                    frame.get("type") == "tick"
                    and frame.get("running") is True
                    and frame.get("speed") == 16
                    and int(frame["tick"]) > baseline_tick
                ):
                    if not advancing_ticks or int(frame["tick"]) > advancing_ticks[-1]:
                        advancing_ticks.append(int(frame["tick"]))
                    if len(advancing_ticks) >= 2:
                        break

            elapsed = time.monotonic() - start_t0
            assert len(advancing_ticks) >= 2
            assert advancing_ticks[1] > advancing_ticks[0] > baseline_tick
            assert elapsed < 5.0
