"""100-tick deterministic integration, spatial, plan, metrics, and replay invariant suite."""

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
from sim.world import WorldMap


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _strip_volatile_latency(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_volatile_latency(val)
            for key, val in value.items()
            if key not in {"latency_ms", "avg_latency_ms", "max_latency_ms"}
        }
    if isinstance(value, list):
        return [_strip_volatile_latency(item) for item in value]
    return value


def test_100_ticks_full_stack_spatial_plan_metrics_and_replay_invariants(tmp_path: Path) -> None:
    """Run 100 offline ticks with mock LLM/embeddings and verify all system invariants."""
    db_path = tmp_path / "sim_100.db"
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
        non_hold_ticks_pending_replan: dict[str, int] = {}
        replan_cleared_at: dict[str, int] = {}
        distinct_positions: dict[str, set[tuple[int, int]]] = {
            agent_id: {(agent.x, agent.y)} for agent_id, agent in engine.agents.items()
        }

        for step_idx in range(1, 101):
            payload = client.portal.call(engine.step_once)
            assert payload.tick == step_idx
            assert len(payload.agents) == 8

            for agent_id, agent in engine.agents.items():
                distinct_positions[agent_id].add((agent.x, agent.y))

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
                    f"Agent {agent_id} collided with non-walkable tile {(agent.x, agent.y)} "
                    f"at tick {step_idx}"
                )

                if agent.path:
                    prev_tile = (agent.x, agent.y)
                    for path_tile in agent.path:
                        assert world.is_walkable(*path_tile), (
                            f"Agent {agent_id} planned non-walkable path tile {path_tile} "
                            f"at tick {step_idx}"
                        )
                        assert _manhattan(prev_tile, path_tile) == 1, (
                            f"Agent {agent_id} path step {prev_tile} -> {path_tile} is not "
                            f"4-way adjacent at tick {step_idx}"
                        )
                        prev_tile = path_tile

                plan_state = engine.brains[agent_id].plan_state
                if agent.conversation_hold_ticks == 0:
                    assert plan_state is not None, (
                        f"Agent {agent_id} missing plan_state at tick {step_idx}"
                    )
                if plan_state is not None:
                    assert len(plan_state.daily_items) >= 1
                    for block in plan_state.daily_items:
                        assert 0 <= block.start_hour < block.end_hour <= 24
                        assert block.location in world.locations
                    serialized = json.loads(engine.get_serialized_plan_json(agent_id))
                    assert isinstance(serialized, list) and len(serialized) >= 1

            if step_idx > 35:
                for agent_id in affected_agents:
                    agent = engine.agents[agent_id]
                    if agent.needs_replan:
                        if agent.conversation_hold_ticks == 0:
                            non_hold_ticks_pending_replan[agent_id] += 1
                            assert non_hold_ticks_pending_replan[agent_id] <= 6, (
                                f"Agent {agent_id} failed to clear needs_replan within 6 "
                                f"non-hold ticks after tick-35 event (tick {step_idx})"
                            )
                    elif agent_id not in replan_cleared_at:
                        replan_cleared_at[agent_id] = step_idx

            if step_idx == 35:
                event_resp = client.post(
                    "/events",
                    json={
                        "text": "Sudden spice delivery arrived at the Bakery",
                        "location": "Bakery",
                    },
                )
                assert event_resp.status_code == 200
                event_data = event_resp.json()
                assert isinstance(event_data["id"], int)
                assert event_data["tick"] == 35
                assert event_data["location"] == "Bakery"
                injected_event_id = event_data["id"]
                affected_agents = list(event_data["affected_agents"])
                assert 1 <= len(affected_agents) < 8
                non_hold_ticks_pending_replan = {aid: 0 for aid in affected_agents}
                for aid in affected_agents:
                    assert engine.agents[aid].needs_replan is True

        assert set(replan_cleared_at) == set(affected_agents)
        assert all(tick_num < 100 for tick_num in replan_cleared_at.values())
        assert all(not engine.agents[aid].needs_replan for aid in affected_agents)

        # Post-100-tick behavioral & spatial exploration outcomes.
        assert all(len(agent.visited_locations) >= 1 for agent in engine.agents.values())
        visited_including_origin = [
            len({agent.home_location} | agent.visited_locations)
            for agent in engine.agents.values()
        ]
        assert sum(count >= 2 for count in visited_including_origin) >= 6, (
            f"Expected >= 6 agents to visit >= 2 locations, got {visited_including_origin!r}"
        )
        moved_tile_counts = [len(coords) for coords in distinct_positions.values()]
        assert sum(count >= 15 for count in moved_tile_counts) >= 6, (
            f"Expected >= 6 agents to traverse >= 15 distinct tiles, got {moved_tile_counts!r}"
        )

        conversations = client.portal.call(memory_store.list_conversations)
        assert len(conversations) >= 1

        rel_resp = client.get("/relationships")
        assert rel_resp.status_code == 200
        rel_data = rel_resp.json()
        assert len(rel_data["nodes"]) == 8
        assert len(rel_data["edges"]) >= 1
        for edge in rel_data["edges"]:
            assert edge["agent_a"] < edge["agent_b"]
            assert isinstance(edge["notes"], str) and edge["notes"].strip() != ""
            assert -1.0 <= edge["affinity"] <= 1.0

        # Metrics API vs SQLite llm_calls verification.
        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200
        metrics = metrics_resp.json()

        with closing(sqlite3.connect(str(db_path))) as conn:
            row = conn.execute(
                "SELECT COUNT(*), "
                "COALESCE(SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END), 0), "
                "COALESCE(SUM(tokens_in), 0), "
                "COALESCE(SUM(tokens_out), 0), "
                "COALESCE(SUM(cost_est), 0.0) "
                "FROM llm_calls"
            ).fetchone()
            assert row is not None
            db_calls = int(row[0])
            db_cache_hits = int(row[1])
            db_tokens_in = int(row[2])
            db_tokens_out = int(row[3])
            db_cost_est = float(row[4])

        assert metrics["tick"] == 100
        assert metrics["day"] == 1
        assert metrics["total_calls"] == db_calls
        assert metrics["cache_hits"] == db_cache_hits
        assert metrics["tokens_in"] == db_tokens_in
        assert metrics["tokens_out"] == db_tokens_out
        assert metrics["total_tokens"] == db_tokens_in + db_tokens_out
        assert metrics["cost_est"] == pytest.approx(db_cost_est)
        assert 0 < metrics["total_calls"] < 400
        assert metrics["budget_tokens_used"] <= metrics["daily_token_limit"]
        assert metrics["budget_cost_used"] <= metrics["daily_budget_usd"]
        assert metrics["avg_latency_ms"] >= 0.0
        assert metrics["max_latency_ms"] >= metrics["avg_latency_ms"]
        assert len(metrics["by_purpose"]) >= 1
        assert len(metrics["by_model"]) >= 1
        assert len(metrics["history"]) >= 1
        assert metrics["history"][-1]["cumulative_tokens"] == (
            metrics["tokens_in"] + metrics["tokens_out"]
        )

        # Replay index and JSONL frame integrity verification.
        replay_index_resp = client.get("/replay")
        assert replay_index_resp.status_code == 200
        replay_index = replay_index_resp.json()
        assert replay_index["current_day"] == 1
        day_one_summaries = [item for item in replay_index["days"] if item["day"] == 1]
        assert len(day_one_summaries) == 1
        assert day_one_summaries[0]["tick_count"] == 101
        assert day_one_summaries[0]["first_tick"] == 0
        assert day_one_summaries[0]["last_tick"] == 100

        replay_day_resp = client.get("/replay/1")
        assert replay_day_resp.status_code == 200
        replay_day = replay_day_resp.json()
        assert replay_day["day"] == 1
        assert replay_day["tick_count"] == 101
        assert replay_day["first_tick"] == 0
        assert replay_day["last_tick"] == 100

        frames: list[dict[str, Any]] = replay_day["frames"]
        assert all(frame.get("type") in ALLOWED_REPLAY_FRAME_TYPES for frame in frames)
        assert all(frame.get("type") != "metrics" for frame in frames)
        tick_frames = [frame for frame in frames if frame.get("type") == "tick"]
        assert [frame["tick"] for frame in tick_frames] == list(range(101))
        frame_ticks = [frame["tick"] for frame in frames]
        assert frame_ticks == sorted(frame_ticks)

        assert any(
            frame.get("type") == "event"
            and frame.get("id") == injected_event_id
            and frame.get("tick") == 35
            and frame.get("location") == "Bakery"
            for frame in frames
        )
        assert any(frame.get("type") == "dialogue" for frame in frames)


def _run_fixed_seed_simulation(run_dir: Path) -> dict[str, Any]:
    db_path = run_dir / "sim_determinism.db"
    replay_dir = run_dir / "logs"
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
        memory_store: MemoryStore = app.state.memory_store

        for step_idx in range(1, 41):
            payload = client.portal.call(engine.step_once)
            assert payload.tick == step_idx
            if step_idx == 15:
                ev_resp = client.post(
                    "/events",
                    json={
                        "text": "Sudden spice delivery arrived at the Bakery",
                        "location": "Bakery",
                    },
                )
                assert ev_resp.status_code == 200

        agent_states = {
            agent_id: {
                "x": agent.x,
                "y": agent.y,
                "current_action": agent.current_action,
                "mood": agent.mood,
                "current_plan_json": engine.get_serialized_plan_json(agent_id),
            }
            for agent_id, agent in sorted(engine.agents.items())
        }

        conversations = sorted(
            client.portal.call(memory_store.list_conversations),
            key=lambda conv: (conv.tick_start, conv.participants),
        )
        conversation_records = [
            {
                "tick_start": conv.tick_start,
                "participants": conv.participants,
                "transcript_json": conv.transcript_json,
                "summary": conv.summary,
            }
            for conv in conversations
        ]

        relationships_resp = client.get("/relationships")
        assert relationships_resp.status_code == 200
        relationships = relationships_resp.json()

        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200
        metrics_structured = _strip_volatile_latency(metrics_resp.json())

        replay_resp = client.get("/replay/1")
        assert replay_resp.status_code == 200
        replay_frames = _strip_volatile_latency(replay_resp.json()["frames"])

    with closing(sqlite3.connect(str(db_path))) as conn:
        call_rows = conn.execute(
            "SELECT tick, agent_id, purpose, model, tokens_in, tokens_out, cost_est, cache_hit "
            "FROM llm_calls "
            "ORDER BY tick, agent_id, purpose, model, tokens_in, tokens_out, cache_hit"
        ).fetchall()

    return {
        "agents": agent_states,
        "conversation_count": len(conversation_records),
        "conversations": conversation_records,
        "relationships": relationships,
        "llm_calls": call_rows,
        "metrics": metrics_structured,
        "replay_frames": replay_frames,
    }


def test_deterministic_mock_reproducibility_across_runs(tmp_path: Path) -> None:
    """Two isolated runs with seed=42 and identical events produce bit-for-bit identical output."""
    run_a = _run_fixed_seed_simulation(tmp_path / "run_a")
    run_b = _run_fixed_seed_simulation(tmp_path / "run_b")

    assert run_a["agents"] == run_b["agents"]
    assert run_a["conversation_count"] == run_b["conversation_count"]
    assert run_a["conversations"] == run_b["conversations"]
    assert run_a["relationships"] == run_b["relationships"]
    assert run_a["llm_calls"] == run_b["llm_calls"]
    assert run_a["metrics"] == run_b["metrics"]
    assert run_a["replay_frames"] == run_b["replay_frames"]
