"""Full 1,440-tick (Day 1 06:00 -> Day 2 06:00) offline verification test suite."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from memory.store import MemoryStore
from sim.engine import SimulationEngine
from sim.replay import ALLOWED_REPLAY_FRAME_TYPES
from sim.world import GridPos, WorldMap


def _manhattan(a: GridPos, b: GridPos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def test_full_day_1440_tick_simulation_invariants(tmp_path: Path) -> None:
    """Execute a complete 24-hour simulated day offline and verify all behavioral invariants."""
    db_path = tmp_path / "sim_1440.db"
    replay_dir = tmp_path / "logs"
    app = create_app(
        Settings(
            sim_auto_start=False,
            sim_tick_seconds=0.05,
            sim_seed=42,
            llm_provider="mock",
            embedding_provider="mock",
            database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
            replay_log_dir=str(replay_dir),
        )
    )

    with TestClient(app) as client:
        assert client.portal is not None
        engine: SimulationEngine = app.state.engine
        world: WorldMap = app.state.world
        memory_store: MemoryStore = app.state.memory_store

        injected_event_id: int | None = None
        affected_agents: list[str] = []
        non_hold_pending_replan: dict[str, int] = {}
        replan_cleared_at: dict[str, int] = {}
        day1_planned_agents: set[str] = set()
        day2_planned_agents: set[str] = set()
        last_payload = None

        for step_idx in range(1, 1441):
            payload = client.portal.call(engine.step_once)
            last_payload = payload
            assert payload.tick == step_idx
            assert len(payload.agents) == 8

            positions = [(agent.x, agent.y) for agent in engine.agents.values()]
            assert len(set(positions)) == 8, f"Tile overlap at tick {step_idx}: {positions!r}"

            stationary_positions = [
                (agent.x, agent.y)
                for agent in engine.agents.values()
                if agent.dwell_ticks_remaining > 0
                or agent.conversation_hold_ticks > 0
                or not agent.path
            ]
            assert len(set(stationary_positions)) == len(stationary_positions), (
                f"Stationary tile overlap at tick {step_idx}: {stationary_positions!r}"
            )

            for agent_id in sorted(engine.agents):
                agent = engine.agents[agent_id]
                assert world.is_walkable(agent.x, agent.y), (
                    f"Agent {agent_id} on non-walkable tile {(agent.x, agent.y)} at tick {step_idx}"
                )

                if agent.path:
                    prev_tile: GridPos = (agent.x, agent.y)
                    for path_tile in agent.path:
                        assert world.is_walkable(*path_tile), (
                            f"Non-walkable path tile {path_tile} for {agent_id} at tick {step_idx}"
                        )
                        assert _manhattan(prev_tile, path_tile) == 1, (
                            f"Non-4-way step {prev_tile} -> {path_tile} for {agent_id} "
                            f"at tick {step_idx}"
                        )
                        prev_tile = path_tile

                plan_state = engine.brains[agent_id].plan_state
                if agent.conversation_hold_ticks == 0:
                    assert plan_state is not None, (
                        f"Missing plan_state for {agent_id} at tick {step_idx}"
                    )
                if plan_state is not None:
                    if plan_state.day == 1:
                        day1_planned_agents.add(agent_id)
                    elif plan_state.day == 2:
                        day2_planned_agents.add(agent_id)
                    assert len(plan_state.daily_items) >= 1
                    for block in plan_state.daily_items:
                        assert 0 <= block.start_hour < block.end_hour <= 24
                        assert block.location in world.locations

            if step_idx > 380:
                for agent_id in affected_agents:
                    agent = engine.agents[agent_id]
                    if agent.needs_replan:
                        if agent.conversation_hold_ticks == 0:
                            non_hold_pending_replan[agent_id] += 1
                            assert non_hold_pending_replan[agent_id] <= 8, (
                                f"Agent {agent_id} failed to clear needs_replan promptly "
                                f"after tick-380 event (tick {step_idx})"
                            )
                    elif agent_id not in replan_cleared_at:
                        replan_cleared_at[agent_id] = step_idx

            if step_idx == 380:
                ev_resp = client.post(
                    "/events",
                    json={
                        "text": "Sudden fire near the Market spice stalls",
                        "location": "Market",
                    },
                )
                assert ev_resp.status_code == 200
                ev_data = ev_resp.json()
                assert ev_data["tick"] == 380
                assert ev_data["location"] == "Market"
                injected_event_id = int(ev_data["id"])
                affected_agents = list(ev_data["affected_agents"])
                assert 1 <= len(affected_agents) < 8
                non_hold_pending_replan = {aid: 0 for aid in affected_agents}
                for aid in affected_agents:
                    assert engine.agents[aid].needs_replan is True

        assert last_payload is not None
        assert last_payload.tick == 1440
        assert last_payload.sim_time == "Day 2 06:00"
        assert last_payload.day == 2

        assert len(day1_planned_agents) == 8
        assert len(day2_planned_agents) == 8
        for aid in engine.agents:
            plan_state = engine.brains[aid].plan_state
            assert plan_state is not None and plan_state.day == 2
        assert set(replan_cleared_at) == set(affected_agents)
        assert all(not engine.agents[aid].needs_replan for aid in affected_agents)

        conversations = client.portal.call(memory_store.list_conversations)
        assert len(conversations) >= 1
        for conv in conversations:
            turns = json.loads(conv.transcript_json)
            assert isinstance(turns, list)
            assert 1 <= len(turns) <= 6

        rel_resp = client.get("/relationships")
        assert rel_resp.status_code == 200
        rel_data = rel_resp.json()
        assert len(rel_data["nodes"]) == 8
        assert len(rel_data["edges"]) >= 1
        for edge in rel_data["edges"]:
            assert edge["agent_a"] < edge["agent_b"]
            assert -1.0 <= edge["affinity"] <= 1.0

        with closing(sqlite3.connect(str(db_path))) as conn:
            reflection_rows = conn.execute(
                "SELECT metadata_json FROM memories WHERE type = 'reflection'"
            ).fetchall()
            assert len(reflection_rows) >= 1
            for (meta_raw,) in reflection_rows:
                meta = json.loads(str(meta_raw))
                cited_ids = meta.get("cited_memory_ids", [])
                assert isinstance(cited_ids, list) and len(cited_ids) >= 1

            aware_rows = conn.execute(
                "SELECT DISTINCT agent_id FROM memories "
                "WHERE created_tick >= 380 AND LOWER(text) LIKE '%fire%'"
            ).fetchall()
            aware_agents = {str(row[0]) for row in aware_rows}
            assert set(affected_agents).issubset(aware_agents)
            assert len(aware_agents) > len(affected_agents), (
                f"Expected multi-agent rumor propagation beyond {affected_agents!r}, "
                f"got aware={sorted(aware_agents)!r}"
            )

            row = conn.execute(
                "SELECT COUNT(*), "
                "COALESCE(SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END), 0), "
                "COALESCE(SUM(tokens_in), 0), "
                "COALESCE(SUM(tokens_out), 0), "
                "COALESCE(SUM(cost_est), 0.0) "
                "FROM llm_calls"
            ).fetchone()
            assert row is not None
            db_calls, db_cache_hits, db_tin, db_tout, db_cost = (
                int(row[0]),
                int(row[1]),
                int(row[2]),
                int(row[3]),
                float(row[4]),
            )

        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200
        metrics = metrics_resp.json()
        assert metrics["tick"] == 1440
        assert metrics["day"] == 2
        assert metrics["total_calls"] == db_calls
        assert metrics["cache_hits"] == db_cache_hits
        assert metrics["tokens_in"] == db_tin
        assert metrics["tokens_out"] == db_tout
        assert metrics["total_tokens"] == db_tin + db_tout
        assert metrics["cost_est"] == pytest.approx(db_cost)

        replay_index_resp = client.get("/replay")
        assert replay_index_resp.status_code == 200
        replay_index = replay_index_resp.json()
        assert replay_index["current_day"] == 2
        assert [item["day"] for item in replay_index["days"]] == [1, 2]

        day1_resp = client.get("/replay/1")
        day2_resp = client.get("/replay/2")
        assert day1_resp.status_code == 200
        assert day2_resp.status_code == 200
        day1_log = day1_resp.json()
        day2_log = day2_resp.json()

        assert day1_log["tick_count"] == 1080
        assert day1_log["first_tick"] == 0
        assert day1_log["last_tick"] == 1079

        assert day2_log["tick_count"] == 361
        assert day2_log["first_tick"] == 1080
        assert day2_log["last_tick"] == 1440

        day1_frames: list[dict[str, Any]] = day1_log["frames"]
        day2_frames: list[dict[str, Any]] = day2_log["frames"]
        for frames in (day1_frames, day2_frames):
            assert all(frame.get("type") in ALLOWED_REPLAY_FRAME_TYPES for frame in frames)
            ticks_seq = [int(frame["tick"]) for frame in frames]
            assert ticks_seq == sorted(ticks_seq)

        all_frames = [*day1_frames, *day2_frames]
        present_types = {str(frame.get("type")) for frame in all_frames}
        assert {"tick", "event", "dialogue", "reflection"}.issubset(present_types)
        assert any(
            frame.get("type") == "event"
            and frame.get("id") == injected_event_id
            and frame.get("tick") == 380
            and frame.get("location") == "Market"
            for frame in day1_frames
        )
