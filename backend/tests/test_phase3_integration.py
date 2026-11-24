"""Offline end-to-end Phase 3 integration tests for cognitive loop, dialogues, and events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import Database
from app.main import create_app
from llm.gateway import LLMGateway
from llm.providers.mock import MockProvider
from memory.embeddings import EmbeddingService
from memory.retrieval import MemoryRetriever
from memory.store import MemoryStore
from sim.clock import SimClock
from sim.engine import SimulationEngine
from sim.world import GridPos, WorldMap


async def _create_cognitive_engine() -> tuple[
    Database,
    MemoryStore,
    LLMGateway,
    WorldMap,
    SimulationEngine,
]:
    world = WorldMap.from_tiled_json(get_settings().resolved_map_path())
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.init_models()
    embeddings = EmbeddingService.from_mode("mock")
    memory_store = MemoryStore(db=db, embedding_service=embeddings)
    retriever = MemoryRetriever(store=memory_store, embedding_service=embeddings)
    llm_gateway = LLMGateway(provider=MockProvider(seed=42), db=db, seed=42)
    engine = SimulationEngine(
        world=world,
        clock=SimClock(speed=1, base_tick_seconds=0.05),
        seed=42,
        dwell_ticks=4,
        memory_store=memory_store,
        retriever=retriever,
        llm_gateway=llm_gateway,
    )
    await engine.initialize_persistence()
    return db, memory_store, llm_gateway, world, engine


def _place_on_free_adjacent(
    world: WorldMap,
    engine: SimulationEngine,
    agent_id: str,
    target_pos: GridPos,
) -> GridPos:
    occupied = {
        (agent.x, agent.y)
        for other_id, agent in engine.agents.items()
        if other_id != agent_id
    }
    spot = world.find_free_adjacent(target_pos[0], target_pos[1], occupied, max_radius=2)
    assert spot is not None, f"No free adjacent tile near {target_pos}"
    agent = engine.agents[agent_id]
    agent.x, agent.y = spot
    agent.path = []
    return spot


def _move_non_participants_away(
    world: WorldMap,
    engine: SimulationEngine,
    keep_ids: set[str],
    safe_anchor_name: str = "Home_Noah",
) -> None:
    anchor = world.get_location(safe_anchor_name).anchor
    occupied = {
        (agent.x, agent.y)
        for agent_id, agent in engine.agents.items()
        if agent_id in keep_ids
    }
    for agent_id in sorted(engine.agents):
        if agent_id in keep_ids:
            continue
        agent = engine.agents[agent_id]
        if (agent.x, agent.y) not in occupied and all(
            abs(agent.x - engine.agents[keep_id].x) + abs(agent.y - engine.agents[keep_id].y)
            >= 5
            for keep_id in keep_ids
        ):
            occupied.add((agent.x, agent.y))
            continue
        spot = world.find_free_adjacent(anchor[0], anchor[1], occupied, max_radius=5)
        assert spot is not None
        agent.x, agent.y = spot
        agent.path = []
        occupied.add(spot)


@pytest.mark.asyncio
async def test_engine_80_ticks_cognitive_loop_and_dialogue() -> None:
    db, memory_store, llm_gateway, world, engine = await _create_cognitive_engine()
    try:
        emitted_events: list[dict[str, Any]] = []

        async def _capture_event(payload: dict[str, Any]) -> None:
            emitted_events.append(payload)

        engine.register_event_callback(_capture_event)

        for step_idx in range(1, 81):
            payload = await engine.step_once()
            assert payload.tick == step_idx
            assert len(payload.agents) == 8

            positions = [(agent.x, agent.y) for agent in engine.agents.values()]
            assert len(set(positions)) == 8, f"Tile overlap at tick {step_idx}"
            for agent in engine.agents.values():
                assert world.is_walkable(agent.x, agent.y), (
                    f"Agent {agent.id} stepped onto blocked tile {(agent.x, agent.y)}"
                )

        persisted_agents = await memory_store.list_agents()
        assert len(persisted_agents) == 8
        for record in persisted_agents:
            assert record.current_plan_json == engine.get_serialized_plan_json(record.id)
            parsed_plan = json.loads(record.current_plan_json)
            assert isinstance(parsed_plan, list)
            # Initial DailyPlan has 5..8 blocks; mid-day ReplanResponse allows 1..8 blocks.
            assert 1 <= len(parsed_plan) <= 8
            for block in parsed_plan:
                assert {"start_hour", "end_hour", "location", "description"} <= set(
                    block.keys()
                )
                assert block["location"] in world.locations

        dialogue_payloads = [item for item in emitted_events if item.get("type") == "dialogue"]
        conversations = await memory_store.list_conversations()
        assert len(dialogue_payloads) >= 1
        assert len(conversations) >= 1
        assert len(dialogue_payloads) == len(conversations)

        first_dialogue = dialogue_payloads[0]
        assert len(first_dialogue["participants"]) == 2
        assert len(first_dialogue["participant_names"]) == 2
        assert 2 <= len(first_dialogue["turns"]) <= 6
        assert isinstance(first_dialogue["summary"], str) and first_dialogue["summary"]

        usage = await llm_gateway.get_usage_summary()
        # 80 ticks * 8 agents = 640 agent-ticks; lazy planning + cooldowns must avoid explosion.
        assert 16 <= int(usage["total_calls"]) < 260
    finally:
        await db.dispose()


def test_post_events_global_radius_and_validation(tmp_path: Path) -> None:
    db_path = tmp_path / "phase3_events.db"
    app = create_app(
        Settings(
            sim_auto_start=False,
            sim_tick_seconds=0.05,
            database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        )
    )

    with TestClient(app) as client:
        blank_resp = client.post("/events", json={"text": "   ", "location": None})
        assert blank_resp.status_code == 422

        bad_loc_resp = client.post(
            "/events",
            json={"text": "A strange comet appeared", "location": "Mars"},
        )
        assert bad_loc_resp.status_code == 400

        engine: SimulationEngine = app.state.engine

        with client.websocket_connect("/ws") as ws:
            initial_frame = ws.receive_json()
            assert initial_frame["type"] == "tick"

            bakery_resp = client.post(
                "/events",
                json={"text": "A fire broke out in the ovens", "location": "Bakery"},
            )
            assert bakery_resp.status_code == 200
            bakery_data = bakery_resp.json()
            assert bakery_data["id"] is not None
            assert bakery_data["tick"] == 0
            assert bakery_data["location"] == "Bakery"
            assert "aria" in bakery_data["affected_agents"]
            assert "elena" not in bakery_data["affected_agents"]

            assert engine.agents["aria"].needs_replan is True
            assert engine.agents["elena"].needs_replan is False

            ws_bakery_event = ws.receive_json()
            assert ws_bakery_event["type"] == "event"
            assert ws_bakery_event["id"] == bakery_data["id"]
            assert ws_bakery_event["text"] == "A fire broke out in the ovens"
            assert ws_bakery_event["location"] == "Bakery"
            assert ws_bakery_event["affected_agents"] == bakery_data["affected_agents"]

            global_resp = client.post(
                "/events",
                json={"text": "Festival announced tonight", "location": None},
            )
            assert global_resp.status_code == 200
            global_data = global_resp.json()
            assert global_data["location"] is None
            assert set(global_data["affected_agents"]) == set(engine.agents.keys())
            assert all(agent.needs_replan for agent in engine.agents.values())

            ws_global_event = ws.receive_json()
            assert ws_global_event["type"] == "event"
            assert ws_global_event["id"] == global_data["id"]
            assert ws_global_event["text"] == "Festival announced tonight"
            assert ws_global_event["location"] is None
            assert len(ws_global_event["affected_agents"]) == 8

        memory_store: MemoryStore = app.state.memory_store
        assert client.portal is not None
        # Verify EventRecords and witness memories persisted immediately even while paused.
        events = client.portal.call(memory_store.list_events)
        assert len(events) == 2
        assert {event.text for event in events} == {
            "A fire broke out in the ovens",
            "Festival announced tonight",
        }
        aria_memories = client.portal.call(memory_store.list_memories, "aria")
        elena_memories = client.portal.call(memory_store.list_memories, "elena")
        assert any(
            "[EVENT] at Bakery: A fire broke out in the ovens" in m.text and m.importance == 8
            for m in aria_memories
        )
        assert not any("A fire broke out in the ovens" in m.text for m in elena_memories)
        assert any("[EVENT]: Festival announced tonight" in m.text for m in elena_memories)


@pytest.mark.asyncio
async def test_event_triggers_replan_and_multi_hop_rumor_spread() -> None:
    db, memory_store, _gateway, world, engine = await _create_cognitive_engine()
    try:
        emitted_events: list[dict[str, Any]] = []

        async def _capture_event(payload: dict[str, Any]) -> None:
            emitted_events.append(payload)

        engine.register_event_callback(_capture_event)

        # Generate initial daily plans on ticks 1..2.
        await engine.step_once()
        await engine.step_once()

        # Isolate Maya at Home_Elena while Liam and Clara are across town.
        maya = engine.agents["maya"]
        liam = engine.agents["liam"]
        clara = engine.agents["clara"]
        maya.x, maya.y = world.get_location("Home_Elena").anchor
        maya.path = []
        liam.x, liam.y = world.get_location("Home_Noah").anchor
        liam.path = []
        clara.x, clara.y = world.get_location("Home_Liam").anchor
        clara.path = []
        _move_non_participants_away(world, engine, {"maya", "liam", "clara"}, "Home_Liam")

        event_payload = await engine.inject_event(
            "A sudden storm flooded the plaza",
            location="Home_Elena",
            radius=4,
        )
        assert event_payload["affected_agents"] == ["maya"]
        assert maya.needs_replan is True

        # Step tick 3 while Maya is alone so she replans and clears needs_replan.
        await engine.step_once()
        assert maya.needs_replan is False
        maya_plans = await memory_store.list_memories("maya", memory_type="plan")
        assert len(maya_plans) >= 2
        assert any("storm" in plan.text.lower() for plan in maya_plans)
        assert not any(
            "storm" in m.text.lower()
            for m in await memory_store.list_memories("liam")
        )
        assert not any(
            "storm" in m.text.lower()
            for m in await memory_store.list_memories("clara")
        )

        # Hop 1: Bring Liam adjacent to Maya so ConversationManager spreads the event.
        for _ in range(5):
            if maya.conversation_hold_ticks == 0 and liam.conversation_hold_ticks == 0:
                break
            await engine.step_once()
        _move_non_participants_away(world, engine, {"maya", "liam", "clara"}, "Home_Noah")
        _place_on_free_adjacent(world, engine, "liam", (maya.x, maya.y))

        await engine.step_once()
        liam_conv = await memory_store.list_memories("liam", memory_type="conversation")
        assert len(liam_conv) >= 1
        assert any("storm" in mem.text.lower() for mem in liam_conv)
        assert any(
            ev.get("type") == "dialogue" and set(ev["participants"]) == {"maya", "liam"}
            for ev in emitted_events
        )

        # Hop 2: Wait for Liam's conversation hold to end, then bring Clara adjacent to Liam.
        for _ in range(6):
            if liam.conversation_hold_ticks == 0 and clara.conversation_hold_ticks == 0:
                break
            await engine.step_once()
        assert liam.conversation_hold_ticks == 0

        _move_non_participants_away(world, engine, {"liam", "clara"}, "Home_Noah")
        _place_on_free_adjacent(world, engine, "clara", (liam.x, liam.y))

        await engine.step_once()
        clara_conv = await memory_store.list_memories("clara", memory_type="conversation")
        assert len(clara_conv) >= 1
        assert any("storm" in mem.text.lower() for mem in clara_conv)
        assert any(
            ev.get("type") == "dialogue" and set(ev["participants"]) == {"liam", "clara"}
            for ev in emitted_events
        )
        assert len(await memory_store.list_conversations()) >= 2
    finally:
        await db.dispose()
