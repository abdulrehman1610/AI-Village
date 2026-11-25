"""Offline 1,440-tick full-day village simulation runner and empirical telemetry exporter."""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import time
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from llm.gateway import estimate_cost_usd
from sim.engine import SimulationEngine, TickPayload
from sim.replay import ALLOWED_REPLAY_FRAME_TYPES
from sim.world import GridPos, WorldMap

_PLANNING_PURPOSES: frozenset[str] = frozenset(
    {
        "daily_plan",
        "replan",
        "hourly_plan",
        "reflection",
        "salient_questions",
    }
)


@dataclass(frozen=True)
class ScheduledEvent:
    """Mid-day god-mode event injected at a deterministic tick."""

    tick: int
    location: str
    text: str
    topic_key: str
    keywords: tuple[str, ...]


@dataclass
class InvariantStats:
    """Running counts of spatial, A*, and plan invariant checks across all ticks."""

    wall_collisions: int = 0
    tile_overlaps: int = 0
    stationary_overlaps: int = 0
    invalid_path_steps: int = 0
    missing_plan_states: int = 0
    day1_agents_planned: set[str] = field(default_factory=set)
    day2_agents_planned: set[str] = field(default_factory=set)


@dataclass
class EventTracker:
    """Tracks god-mode event injection impact and replan completion timing."""

    spec: ScheduledEvent
    event_id: int | None = None
    sim_time: str = ""
    affected_agents: list[str] = field(default_factory=list)
    non_hold_pending: dict[str, int] = field(default_factory=dict)
    replan_cleared_at: dict[str, int] = field(default_factory=dict)


def _manhattan(a: GridPos, b: GridPos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _is_planning_purpose(purpose: str) -> bool:
    normalized = purpose.strip().lower()
    return normalized in _PLANNING_PURPOSES or "plan" in normalized


def _verify_tick_invariants(
    *,
    step_idx: int,
    payload: TickPayload,
    engine: SimulationEngine,
    world: WorldMap,
    stats: InvariantStats,
    trackers: list[EventTracker],
) -> None:
    if payload.tick != step_idx:
        raise AssertionError(f"Expected tick {step_idx}, got {payload.tick}")
    if len(payload.agents) != len(engine.agents):
        raise AssertionError(
            f"Expected {len(engine.agents)} agent snapshots at tick {step_idx}, "
            f"got {len(payload.agents)}"
        )

    positions = [(agent.x, agent.y) for agent in engine.agents.values()]
    if len(set(positions)) != len(engine.agents):
        stats.tile_overlaps += 1
        raise AssertionError(f"Tile overlap at tick {step_idx}: {positions!r}")

    stationary_positions = [
        (agent.x, agent.y)
        for agent in engine.agents.values()
        if agent.dwell_ticks_remaining > 0
        or agent.conversation_hold_ticks > 0
        or not agent.path
    ]
    if len(set(stationary_positions)) != len(stationary_positions):
        stats.stationary_overlaps += 1
        raise AssertionError(
            f"Stationary tile overlap at tick {step_idx}: {stationary_positions!r}"
        )

    for agent_id in sorted(engine.agents):
        agent = engine.agents[agent_id]
        if not world.is_walkable(agent.x, agent.y):
            stats.wall_collisions += 1
            raise AssertionError(
                f"Agent {agent_id} on non-walkable tile {(agent.x, agent.y)} at tick {step_idx}"
            )

        if agent.path:
            prev_tile: GridPos = (agent.x, agent.y)
            for path_tile in agent.path:
                if not world.is_walkable(*path_tile) or _manhattan(prev_tile, path_tile) != 1:
                    stats.invalid_path_steps += 1
                    raise AssertionError(
                        f"Invalid A* path step {prev_tile} -> {path_tile} "
                        f"for {agent_id} at tick {step_idx}"
                    )
                prev_tile = path_tile

        plan_state = engine.brains[agent_id].plan_state
        if plan_state is None and agent.conversation_hold_ticks == 0:
            stats.missing_plan_states += 1
            raise AssertionError(f"Agent {agent_id} missing plan_state at tick {step_idx}")

        if plan_state is not None:
            if plan_state.day == 1:
                stats.day1_agents_planned.add(agent_id)
            elif plan_state.day >= 2:
                stats.day2_agents_planned.add(agent_id)
            for block in plan_state.daily_items:
                if not (0 <= block.start_hour < block.end_hour <= 24):
                    raise AssertionError(
                        f"Invalid plan block hours {block.start_hour}-{block.end_hour} "
                        f"for {agent_id} at tick {step_idx}"
                    )
                if block.location not in world.locations:
                    raise AssertionError(
                        f"Unknown plan location {block.location!r} for {agent_id} "
                        f"at tick {step_idx}"
                    )

    for tracker in trackers:
        if tracker.event_id is None or step_idx <= tracker.spec.tick:
            continue
        for agent_id in tracker.affected_agents:
            agent = engine.agents[agent_id]
            if agent.needs_replan:
                if agent.conversation_hold_ticks == 0:
                    tracker.non_hold_pending[agent_id] = (
                        tracker.non_hold_pending.get(agent_id, 0) + 1
                    )
                    if tracker.non_hold_pending[agent_id] > 8:
                        raise AssertionError(
                            f"Agent {agent_id} failed to clear needs_replan within 8 non-hold "
                            f"ticks after tick-{tracker.spec.tick} event (tick {step_idx})"
                        )
            elif agent_id not in tracker.replan_cleared_at:
                tracker.replan_cleared_at[agent_id] = step_idx


def _collect_sqlite_telemetry(
    db_path: Path,
    event_trackers: list[EventTracker],
) -> dict[str, Any]:
    with closing(sqlite3.connect(str(db_path))) as conn:
        memory_type_rows = conn.execute(
            "SELECT type, COUNT(*) FROM memories GROUP BY type ORDER BY type"
        ).fetchall()
        memories_by_type = {str(row[0]): int(row[1]) for row in memory_type_rows}
        total_memories = sum(memories_by_type.values())

        per_agent_rows = conn.execute(
            "SELECT agent_id, COUNT(*) FROM memories GROUP BY agent_id ORDER BY agent_id"
        ).fetchall()
        memories_per_agent = {str(row[0]): int(row[1]) for row in per_agent_rows}

        conv_rows = conn.execute(
            "SELECT id, tick_start, participants, transcript_json FROM conversations ORDER BY id"
        ).fetchall()
        turn_counts: list[int] = []
        unique_pairs: set[tuple[str, str]] = set()
        for _cid, _tick_start, participants_raw, transcript_raw in conv_rows:
            participants_parsed = json.loads(str(participants_raw))
            if isinstance(participants_parsed, list) and len(participants_parsed) >= 2:
                pair_a, pair_b = str(participants_parsed[0]), str(participants_parsed[1])
                unique_pairs.add((pair_a, pair_b) if pair_a <= pair_b else (pair_b, pair_a))
            transcript_parsed = json.loads(str(transcript_raw))
            if isinstance(transcript_parsed, list):
                turn_counts.append(len(transcript_parsed))

        db_event_count_row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        db_event_count = int(db_event_count_row[0]) if db_event_count_row is not None else 0

        reflection_rows = conn.execute(
            "SELECT agent_id, created_tick, text, metadata_json "
            "FROM memories WHERE type = 'reflection' ORDER BY created_tick, id"
        ).fetchall()
        reflected_agents: set[str] = set()
        cited_counts: list[int] = []
        unique_cited_ids: set[int] = set()
        for agent_id, _tick, _text, meta_raw in reflection_rows:
            reflected_agents.add(str(agent_id))
            meta_parsed = json.loads(str(meta_raw))
            if isinstance(meta_parsed, dict):
                cited_raw = meta_parsed.get("cited_memory_ids", [])
                if isinstance(cited_raw, list):
                    valid_ids = [int(mid) for mid in cited_raw if isinstance(mid, int)]
                    cited_counts.append(len(valid_ids))
                    unique_cited_ids.update(valid_ids)

        llm_agg_row = conn.execute(
            "SELECT COUNT(*), "
            "COALESCE(SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(tokens_in), 0), "
            "COALESCE(SUM(tokens_out), 0), "
            "COALESCE(SUM(cost_est), 0.0) "
            "FROM llm_calls"
        ).fetchone()
        assert llm_agg_row is not None
        llm_purpose_rows = conn.execute(
            "SELECT purpose, COUNT(*), "
            "COALESCE(SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(tokens_in), 0), "
            "COALESCE(SUM(tokens_out), 0) "
            "FROM llm_calls GROUP BY purpose ORDER BY COUNT(*) DESC, purpose ASC"
        ).fetchall()

        rumor_propagation: dict[str, Any] = {}
        all_memory_texts = conn.execute(
            "SELECT agent_id, text, created_tick FROM memories ORDER BY created_tick, id"
        ).fetchall()
        for tracker in event_trackers:
            if tracker.event_id is None:
                continue
            aware_agents: set[str] = set()
            first_seen_tick: dict[str, int] = {}
            for agent_id_val, text_val, created_tick_val in all_memory_texts:
                lowered = str(text_val).lower()
                tick_int = int(created_tick_val)
                if tick_int >= tracker.spec.tick and any(
                    kw in lowered for kw in tracker.spec.keywords
                ):
                    aid = str(agent_id_val)
                    aware_agents.add(aid)
                    if aid not in first_seen_tick:
                        first_seen_tick[aid] = tick_int

            initial_set = set(tracker.affected_agents)
            rumor_propagation[tracker.spec.topic_key] = {
                "event_tick": tracker.spec.tick,
                "location": tracker.spec.location,
                "text": tracker.spec.text,
                "initial_affected_agents": sorted(initial_set),
                "initial_count": len(initial_set),
                "final_aware_agents": sorted(aware_agents),
                "final_count": len(aware_agents),
                "secondary_spread_agents": sorted(aware_agents - initial_set),
                "spread_delta": len(aware_agents - initial_set),
                "first_seen_tick_by_agent": dict(sorted(first_seen_tick.items())),
            }

    planning_tokens_in = 0
    planning_tokens_out = 0
    routine_tokens_in = 0
    routine_tokens_out = 0
    tiered_cost_usd = 0.0
    sqlite_by_purpose: list[dict[str, Any]] = []

    for purpose_raw, calls_raw, cache_raw, tin_raw, tout_raw in llm_purpose_rows:
        purpose_str = str(purpose_raw)
        tin = int(tin_raw)
        tout = int(tout_raw)
        is_plan = _is_planning_purpose(purpose_str)
        projected_model = "gemini-2.5-pro" if is_plan else "gemini-2.5-flash"
        projected_cost = estimate_cost_usd(projected_model, tin, tout)
        tiered_cost_usd += projected_cost
        if is_plan:
            planning_tokens_in += tin
            planning_tokens_out += tout
        else:
            routine_tokens_in += tin
            routine_tokens_out += tout
        sqlite_by_purpose.append(
            {
                "purpose": purpose_str,
                "calls": int(calls_raw),
                "cache_hits": int(cache_raw),
                "tokens_in": tin,
                "tokens_out": tout,
                "projected_model": projected_model,
                "projected_cost_usd": round(projected_cost, 6),
            }
        )

    total_tin = int(llm_agg_row[2])
    total_tout = int(llm_agg_row[3])
    all_flash_cost_usd = estimate_cost_usd("gemini-2.5-flash", total_tin, total_tout)

    return {
        "memories": {
            "total": total_memories,
            "by_type": memories_by_type,
            "per_agent_counts": memories_per_agent,
        },
        "conversations": {
            "total": len(conv_rows),
            "turn_count_min": min(turn_counts) if turn_counts else 0,
            "turn_count_max": max(turn_counts) if turn_counts else 0,
            "turn_count_avg": (
                round(sum(turn_counts) / len(turn_counts), 2) if turn_counts else 0.0
            ),
            "unique_pairs": len(unique_pairs),
        },
        "db_event_count": db_event_count,
        "reflections": {
            "total_memories": len(reflection_rows),
            "agents_reflected": sorted(reflected_agents),
            "agents_reflected_count": len(reflected_agents),
            "cited_reflections_count": sum(1 for count in cited_counts if count > 0),
            "unique_cited_memory_ids": len(unique_cited_ids),
            "min_citations_per_reflection": min(cited_counts) if cited_counts else 0,
            "max_citations_per_reflection": max(cited_counts) if cited_counts else 0,
        },
        "rumor_propagation": rumor_propagation,
        "sqlite_llm": {
            "total_calls": int(llm_agg_row[0]),
            "cache_hits": int(llm_agg_row[1]),
            "tokens_in": total_tin,
            "tokens_out": total_tout,
            "cost_est": float(llm_agg_row[4]),
            "by_purpose": sqlite_by_purpose,
            "projected_gemini_cost": {
                "tiered_flash_pro_usd": round(tiered_cost_usd, 6),
                "all_flash_usd": round(all_flash_cost_usd, 6),
                "planning_tokens_in": planning_tokens_in,
                "planning_tokens_out": planning_tokens_out,
                "routine_tokens_in": routine_tokens_in,
                "routine_tokens_out": routine_tokens_out,
            },
        },
    }


def _collect_replay_telemetry(client: TestClient) -> dict[str, Any]:
    replay_index_resp = client.get("/replay")
    if replay_index_resp.status_code != 200:
        raise AssertionError(f"GET /replay failed: {replay_index_resp.status_code}")
    replay_index_raw = replay_index_resp.json()
    if not isinstance(replay_index_raw, dict):
        raise AssertionError("Unexpected /replay payload type")

    raw_days = replay_index_raw.get("days", [])
    day_summaries: list[dict[str, Any]] = (
        [dict(item) for item in raw_days if isinstance(item, dict)]
        if isinstance(raw_days, list)
        else []
    )
    frame_types_by_day: dict[str, dict[str, int]] = {}
    tick_bounds_by_day: dict[str, dict[str, int | None]] = {}

    for summary in day_summaries:
        day_num = int(summary["day"])
        day_resp = client.get(f"/replay/{day_num}")
        if day_resp.status_code != 200:
            raise AssertionError(f"GET /replay/{day_num} failed: {day_resp.status_code}")
        day_raw = day_resp.json()
        if not isinstance(day_raw, dict):
            raise AssertionError(f"Unexpected /replay/{day_num} payload type")
        frames_raw = day_raw.get("frames", [])
        frames = (
            [frame for frame in frames_raw if isinstance(frame, dict)]
            if isinstance(frames_raw, list)
            else []
        )
        type_counts: Counter[str] = Counter()
        frame_ticks: list[int] = []
        for frame in frames:
            frame_type = str(frame.get("type", ""))
            if frame_type not in ALLOWED_REPLAY_FRAME_TYPES:
                raise AssertionError(
                    f"Disallowed replay frame type {frame_type!r} in day {day_num}"
                )
            type_counts[frame_type] += 1
            tick_val = frame.get("tick")
            if isinstance(tick_val, int) and not isinstance(tick_val, bool):
                frame_ticks.append(tick_val)

        if frame_ticks != sorted(frame_ticks):
            raise AssertionError(f"Replay frames for day {day_num} are not sorted by tick")

        frame_types_by_day[f"day_{day_num}"] = dict(sorted(type_counts.items()))
        tick_bounds_by_day[f"day_{day_num}"] = {
            "tick_count": int(day_raw.get("tick_count", 0)),
            "first_tick": day_raw.get("first_tick"),
            "last_tick": day_raw.get("last_tick"),
        }

    return {
        "current_day": int(replay_index_raw.get("current_day", 1)),
        "days_recorded": [int(item["day"]) for item in day_summaries],
        "day_summaries": day_summaries,
        "frame_types_by_day": frame_types_by_day,
        "tick_bounds_by_day": tick_bounds_by_day,
    }


def _collect_relationship_telemetry(client: TestClient) -> dict[str, Any]:
    rel_resp = client.get("/relationships")
    if rel_resp.status_code != 200:
        raise AssertionError(f"GET /relationships failed: {rel_resp.status_code}")
    rel_raw = rel_resp.json()
    if not isinstance(rel_raw, dict):
        raise AssertionError("Unexpected /relationships payload type")

    nodes_raw = rel_raw.get("nodes", [])
    edges_raw = rel_raw.get("edges", [])
    nodes = (
        [dict(n) for n in nodes_raw if isinstance(n, dict)]
        if isinstance(nodes_raw, list)
        else []
    )
    edges = (
        [dict(e) for e in edges_raw if isinstance(e, dict)]
        if isinstance(edges_raw, list)
        else []
    )

    affinities: list[float] = []
    for edge in edges:
        if str(edge["agent_a"]) >= str(edge["agent_b"]):
            raise AssertionError(f"Non-canonical relationship edge ordering: {edge!r}")
        aff = float(edge["affinity"])
        if not (-1.0 <= aff <= 1.0):
            raise AssertionError(f"Affinity out of bounds: {aff}")
        affinities.append(aff)

    return {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "affinity_min": round(min(affinities), 4) if affinities else 0.0,
        "affinity_max": round(max(affinities), 4) if affinities else 0.0,
        "affinity_avg": round(sum(affinities) / len(affinities), 4) if affinities else 0.0,
        "positive_edges": sum(1 for aff in affinities if aff > 0.0),
        "negative_edges": sum(1 for aff in affinities if aff < 0.0),
        "neutral_edges": sum(1 for aff in affinities if aff == 0.0),
        "edges": edges,
    }


def run_day_simulation(
    *,
    ticks: int = 1440,
    seed: int = 42,
    replay_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute an offline multi-tick simulation, assert invariants, and return telemetry."""
    if ticks < 1:
        raise ValueError(f"ticks must be >= 1, got {ticks}")

    scheduled_events = [
        ScheduledEvent(
            tick=380,
            location="Market",
            text="Sudden fire near the Market spice stalls",
            topic_key="market_fire",
            keywords=("fire", "spice stalls"),
        ),
        ScheduledEvent(
            tick=440,
            location="Bakery",
            text="Rumor spreads that Maya hid rare saffron loaves at the Bakery",
            topic_key="bakery_saffron_rumor",
            keywords=("saffron", "rumor"),
        ),
    ]
    trackers = [EventTracker(spec=spec) for spec in scheduled_events]

    with tempfile.TemporaryDirectory(prefix="ai_village_day_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        db_path = tmp_dir / "day_sim.db"
        effective_replay_dir = replay_dir if replay_dir is not None else (tmp_dir / "logs")
        effective_replay_dir.mkdir(parents=True, exist_ok=True)

        app = create_app(
            Settings(
                sim_auto_start=False,
                sim_tick_seconds=0.05,
                sim_seed=seed,
                llm_provider="mock",
                embedding_provider="mock",
                database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
                replay_log_dir=str(effective_replay_dir),
            )
        )

        stats = InvariantStats()
        start_time = time.perf_counter()

        with TestClient(app) as client:
            if client.portal is None:
                raise RuntimeError("TestClient portal is unavailable")
            engine: SimulationEngine = app.state.engine
            world: WorldMap = app.state.world
            start_sim_time = engine.clock.sim_time_str

            last_payload: TickPayload | None = None
            for step_idx in range(1, ticks + 1):
                payload = client.portal.call(engine.step_once)
                last_payload = payload
                _verify_tick_invariants(
                    step_idx=step_idx,
                    payload=payload,
                    engine=engine,
                    world=world,
                    stats=stats,
                    trackers=trackers,
                )

                for tracker in trackers:
                    if step_idx == tracker.spec.tick:
                        resp = client.post(
                            "/events",
                            json={
                                "text": tracker.spec.text,
                                "location": tracker.spec.location,
                            },
                        )
                        if resp.status_code != 200:
                            raise AssertionError(
                                f"POST /events failed at tick {step_idx}: "
                                f"{resp.status_code} {resp.text}"
                            )
                        ev_data = resp.json()
                        if not isinstance(ev_data, dict):
                            raise AssertionError("Unexpected /events response payload")
                        tracker.event_id = int(ev_data["id"])
                        tracker.sim_time = str(ev_data["sim_time"])
                        raw_affected = ev_data.get("affected_agents", [])
                        tracker.affected_agents = (
                            [str(aid) for aid in raw_affected]
                            if isinstance(raw_affected, list)
                            else []
                        )
                        tracker.non_hold_pending = {aid: 0 for aid in tracker.affected_agents}

            elapsed_seconds = round(time.perf_counter() - start_time, 3)

            metrics_resp = client.get("/metrics")
            if metrics_resp.status_code != 200:
                raise AssertionError(f"GET /metrics failed: {metrics_resp.status_code}")
            metrics_raw = metrics_resp.json()
            if not isinstance(metrics_raw, dict):
                raise AssertionError("Unexpected /metrics response payload")
            metrics_data: dict[str, Any] = dict(metrics_raw)

            relationships_summary = _collect_relationship_telemetry(client)
            replay_summary = _collect_replay_telemetry(client)
            sqlite_summary = _collect_sqlite_telemetry(db_path, trackers)

            agents_final = []
            for aid in sorted(engine.agents):
                agent = engine.agents[aid]
                brain = engine.brains[aid]
                plan_state = brain.plan_state
                agents_final.append(
                    {
                        "id": agent.id,
                        "name": agent.name,
                        "role": agent.role,
                        "x": agent.x,
                        "y": agent.y,
                        "mood": agent.mood,
                        "current_action": agent.current_action,
                        "visited_locations_count": len(agent.visited_locations),
                        "accumulated_importance": brain.accumulated_importance,
                        "plan_day": plan_state.day if plan_state is not None else None,
                    }
                )

    sqlite_llm = sqlite_summary["sqlite_llm"]
    db_parity_ok = (
        int(metrics_data["total_calls"]) == int(sqlite_llm["total_calls"])
        and int(metrics_data["cache_hits"]) == int(sqlite_llm["cache_hits"])
        and int(metrics_data["tokens_in"]) == int(sqlite_llm["tokens_in"])
        and int(metrics_data["tokens_out"]) == int(sqlite_llm["tokens_out"])
    )
    if not db_parity_ok:
        raise AssertionError("GET /metrics aggregates do not match SQLite llm_calls aggregates")

    by_purpose_list = metrics_data.get("by_purpose", [])
    purpose_calls: dict[str, int] = (
        {
            str(item["purpose"]): int(item["calls"])
            for item in by_purpose_list
            if isinstance(item, dict)
        }
        if isinstance(by_purpose_list, list)
        else {}
    )

    end_sim_time = last_payload.sim_time if last_payload is not None else start_sim_time
    end_day = last_payload.day if last_payload is not None else 1

    return {
        "ticks_completed": ticks,
        "seed": seed,
        "start_sim_time": start_sim_time,
        "end_sim_time": end_sim_time,
        "end_day": end_day,
        "wall_clock_seconds": elapsed_seconds,
        "ms_per_tick": round((elapsed_seconds * 1000.0) / ticks, 2),
        "invariants": {
            "wall_collisions": stats.wall_collisions,
            "tile_overlaps": stats.tile_overlaps,
            "stationary_overlaps": stats.stationary_overlaps,
            "invalid_path_steps": stats.invalid_path_steps,
            "missing_plan_states": stats.missing_plan_states,
            "all_passed": (
                stats.wall_collisions == 0
                and stats.tile_overlaps == 0
                and stats.stationary_overlaps == 0
                and stats.invalid_path_steps == 0
                and stats.missing_plan_states == 0
            ),
        },
        "plans": {
            "day1_agents_planned": sorted(stats.day1_agents_planned),
            "day1_agents_planned_count": len(stats.day1_agents_planned),
            "day2_agents_planned": sorted(stats.day2_agents_planned),
            "day2_agents_planned_count": len(stats.day2_agents_planned),
            "total_plan_memories": int(sqlite_summary["memories"]["by_type"].get("plan", 0)),
            "daily_plan_calls": purpose_calls.get("daily_plan", 0),
            "replan_calls": purpose_calls.get("replan", 0),
            "action_decomposition_calls": purpose_calls.get("action_decomposition", 0),
        },
        "events": {
            "db_event_count": sqlite_summary["db_event_count"],
            "injected": [
                {
                    "id": tracker.event_id,
                    "tick": tracker.spec.tick,
                    "sim_time": tracker.sim_time,
                    "location": tracker.spec.location,
                    "text": tracker.spec.text,
                    "affected_agents": tracker.affected_agents,
                    "replan_cleared_at": tracker.replan_cleared_at,
                }
                for tracker in trackers
                if tracker.event_id is not None
            ],
        },
        "memories": sqlite_summary["memories"],
        "conversations": sqlite_summary["conversations"],
        "rumor_propagation": sqlite_summary["rumor_propagation"],
        "reflections": sqlite_summary["reflections"],
        "relationships": relationships_summary,
        "llm": {
            "total_calls": int(metrics_data["total_calls"]),
            "cache_hits": int(metrics_data["cache_hits"]),
            "cache_hit_rate": round(float(metrics_data["cache_hit_rate"]), 4),
            "tokens_in": int(metrics_data["tokens_in"]),
            "tokens_out": int(metrics_data["tokens_out"]),
            "total_tokens": int(metrics_data["total_tokens"]),
            "cost_est": float(metrics_data["cost_est"]),
            "avg_latency_ms": float(metrics_data["avg_latency_ms"]),
            "max_latency_ms": float(metrics_data["max_latency_ms"]),
            "daily_budget_usd": float(metrics_data["daily_budget_usd"]),
            "daily_token_limit": int(metrics_data["daily_token_limit"]),
            "budget_day": int(metrics_data["budget_day"]),
            "budget_tokens_used": int(metrics_data["budget_tokens_used"]),
            "budget_cost_used": float(metrics_data["budget_cost_used"]),
            "by_purpose": metrics_data["by_purpose"],
            "by_model": metrics_data["by_model"],
            "sqlite_by_purpose": sqlite_llm["by_purpose"],
            "db_parity_ok": db_parity_ok,
            "projected_gemini_cost": sqlite_llm["projected_gemini_cost"],
        },
        "replay": replay_summary,
        "agents_final": agents_final,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a deterministic offline AI Village simulation and emit telemetry JSON."
    )
    parser.add_argument("--ticks", type=int, default=1440, help="Number of ticks to execute.")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic simulation seed.")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional output path for the structured telemetry JSON summary.",
    )
    parser.add_argument(
        "--replay-dir",
        type=Path,
        default=None,
        help="Optional replay log directory (uses a TemporaryDirectory if omitted).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    telemetry = run_day_simulation(
        ticks=args.ticks,
        seed=args.seed,
        replay_dir=args.replay_dir,
    )
    rendered = json.dumps(telemetry, indent=2) + "\n"
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered, encoding="utf-8")
        print(
            f"Wrote {args.ticks}-tick empirical telemetry to {args.output_json} "
            f"(calls={telemetry['llm']['total_calls']}, "
            f"conversations={telemetry['conversations']['total']}, "
            f"reflections={telemetry['reflections']['total_memories']})"
        )
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
