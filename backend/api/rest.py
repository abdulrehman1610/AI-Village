"""REST API endpoints exposing authoritative village health, world, and agent state."""

from __future__ import annotations

import json
from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi import Path as FastAPIPath
from pydantic import BaseModel, Field, field_validator

from llm.gateway import LLMGateway, MetricsSnapshot
from memory.models import MemoryRecord
from memory.store import MemoryStore
from sim.engine import AgentEntity, AgentSnapshot, SimulationEngine, TickPayload
from sim.replay import ReplayDayLog, ReplayDaySummary, ReplayLogger
from sim.world import NamedLocation, WorldMap

router = APIRouter()


class HealthResponse(BaseModel):
    """Server health and simulation status summary."""

    status: str = "ok"
    tick: int
    sim_time: str
    agents: int
    map_width: int
    map_height: int


class WorldResponse(BaseModel):
    """Static village world metadata and named locations."""

    width: int
    height: int
    tile_size: int
    locations: list[NamedLocation]


class InjectEventRequest(BaseModel):
    """Request body for injecting a god-mode event into the simulation."""

    text: str = Field(min_length=1, max_length=500)
    location: str | None = None


class InjectEventResponse(BaseModel):
    """Response payload summarizing the persisted and broadcast god-mode event."""

    id: int | None
    tick: int
    sim_time: str
    text: str
    location: str | None
    affected_agents: list[str]


class SimSpeedRequest(BaseModel):
    """Request body for updating simulation playback speed (1x, 4x, or 16x)."""

    speed: Literal[1, 4, 16]

    @field_validator("speed", mode="before")
    @classmethod
    def _reject_bool_speed(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("speed must be 1, 4, or 16")
        return value


class SimControlResponse(BaseModel):
    """Authoritative simulation playback and clock state response."""

    running: bool
    speed: int
    tick: int
    sim_time: str
    day: int


class AgentPersonaDTO(BaseModel):
    """Serializable persona profile returned inside AgentDetailResponse."""

    id: str
    name: str
    age: int
    role: str
    traits: list[str]
    bio: str
    home_location: str
    starting_goals: list[str]


class PlanStepDTO(BaseModel):
    """Serializable minute-level action step inside an agent's plan block."""

    duration_minutes: int
    location: str
    action: str
    start_tick: int
    end_tick: int
    arrived: bool


class PlanBlockDTO(BaseModel):
    """Serializable hourly plan block with optional lazy minute decomposition."""

    start_hour: int
    end_hour: int
    location: str
    description: str
    hourly_focus: str | None = None
    actions: list[PlanStepDTO] = Field(default_factory=list)


class AgentPlanDTO(BaseModel):
    """Serializable hierarchical daily plan view for an inspected agent."""

    day: int | None
    active_block_index: int
    active_minute_index: int
    hourly_focus: str | None
    current_step: PlanStepDTO | None
    daily_plan: list[PlanBlockDTO]


class AgentMemoryDTO(BaseModel):
    """JSON-safe episodic memory view omitting raw embedding binary blobs."""

    id: int | None
    type: str
    text: str
    importance: int
    created_tick: int
    last_access_tick: int
    cited_memory_ids: list[int] = Field(default_factory=list)


class AgentRelationshipDTO(BaseModel):
    """Per-agent projected relationship entry toward a specific peer."""

    peer_id: str
    peer_name: str
    affinity: float
    notes: str
    last_interaction_tick: int


class AgentDetailResponse(BaseModel):
    """Comprehensive inspector payload for a single agent."""

    id: str
    name: str
    role: str
    sprite_index: int
    x: int
    y: int
    home_location: str
    current_location: str
    target_location: str | None
    current_action: str
    mood: str
    accumulated_importance: int
    reflection_threshold: int
    persona: AgentPersonaDTO
    plan: AgentPlanDTO
    recent_memories: list[AgentMemoryDTO]
    top_memories: list[AgentMemoryDTO]
    reflections: list[AgentMemoryDTO]
    relationships: list[AgentRelationshipDTO]


class RelationshipNodeDTO(BaseModel):
    """Village agent node metadata for the relationship graph."""

    id: str
    name: str
    role: str
    mood: str


class RelationshipEdgeDTO(BaseModel):
    """Canonical undirected pairwise relationship edge (agent_a < agent_b)."""

    agent_a: str
    agent_b: str
    agent_a_name: str
    agent_b_name: str
    affinity: float
    notes: str
    last_interaction_tick: int


class RelationshipsResponse(BaseModel):
    """Full relationship graph response containing nodes and canonical edges."""

    nodes: list[RelationshipNodeDTO]
    edges: list[RelationshipEdgeDTO]


class ReplayDaysResponse(BaseModel):
    """Available simulation replay days and current authoritative day."""

    current_day: int
    days: list[ReplayDaySummary]


def _get_engine(request: Request) -> SimulationEngine:
    return cast(SimulationEngine, request.app.state.engine)


def _get_world(request: Request) -> WorldMap:
    return cast(WorldMap, request.app.state.world)


def _get_memory_store(request: Request) -> MemoryStore | None:
    return cast(MemoryStore | None, getattr(request.app.state, "memory_store", None))


def _get_llm_gateway(request: Request) -> LLMGateway | None:
    return cast(LLMGateway | None, getattr(request.app.state, "llm_gateway", None))


def _get_replay_logger(request: Request) -> ReplayLogger | None:
    return cast(ReplayLogger | None, getattr(request.app.state, "replay_logger", None))


def _to_sim_control_response(payload: TickPayload) -> SimControlResponse:
    return SimControlResponse(
        running=payload.running,
        speed=payload.speed,
        tick=payload.tick,
        sim_time=payload.sim_time,
        day=payload.day,
    )


def _resolve_agent_location_label(agent: AgentEntity, world: WorldMap) -> str:
    """Resolve an agent's current village location label from map bounds or anchor distance."""
    tile_size = max(1, world.tile_size)
    center_x = (agent.x + 0.5) * tile_size
    center_y = (agent.y + 0.5) * tile_size

    locations = sorted(world.list_locations(), key=lambda loc: loc.name)
    for loc in locations:
        if (
            loc.width > 0
            and loc.height > 0
            and loc.x <= center_x < loc.x + loc.width
            and loc.y <= center_y < loc.y + loc.height
        ):
            return loc.name

    best_name: str | None = None
    best_dist: int | None = None
    for loc in locations:
        dist = abs(agent.x - loc.anchor_x) + abs(agent.y - loc.anchor_y)
        if dist <= 2 and (best_dist is None or dist < best_dist):
            best_dist = dist
            best_name = loc.name
    if best_name is not None:
        return best_name
    return "Village"


def _parse_cited_memory_ids(metadata_json: str) -> list[int]:
    """Safely extract integer cited_memory_ids from a memory's metadata JSON."""
    if not metadata_json:
        return []
    try:
        parsed = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, dict):
        return []
    raw_ids = parsed.get("cited_memory_ids")
    if not isinstance(raw_ids, list):
        return []
    return [
        item
        for item in raw_ids
        if isinstance(item, int) and not isinstance(item, bool)
    ]


def _to_memory_dto(record: MemoryRecord) -> AgentMemoryDTO:
    """Convert a MemoryRecord into a JSON-safe DTO without exposing its binary embedding."""
    return AgentMemoryDTO(
        id=record.id,
        type=record.type,
        text=record.text,
        importance=record.importance,
        created_tick=record.created_tick,
        last_access_tick=record.last_access_tick,
        cited_memory_ids=_parse_cited_memory_ids(record.metadata_json),
    )


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """Return server health, current simulation tick/time, and world dimensions."""
    engine = _get_engine(request)
    return HealthResponse(
        status="ok",
        tick=engine.clock.tick,
        sim_time=engine.clock.sim_time_str,
        agents=len(engine.agents),
        map_width=engine.world.width,
        map_height=engine.world.height,
    )


@router.get("/world", response_model=WorldResponse)
async def get_world(request: Request) -> WorldResponse:
    """Return world dimensions, tile size, and all named locations."""
    world = _get_world(request)
    return WorldResponse(
        width=world.width,
        height=world.height,
        tile_size=world.tile_size,
        locations=world.list_locations(),
    )


@router.get("/agents", response_model=list[AgentSnapshot])
async def get_agents(request: Request) -> list[AgentSnapshot]:
    """Return authoritative snapshots of all agents in the simulation."""
    engine = _get_engine(request)
    return engine.build_tick_payload().agents


@router.get("/agents/{agent_id}", response_model=AgentDetailResponse)
async def get_agent_detail(agent_id: str, request: Request) -> AgentDetailResponse:
    """Return full inspector state for a single agent, or 404 when unknown."""
    engine = _get_engine(request)
    agent = engine.agents.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id!r}")

    world = _get_world(request)
    memory_store = _get_memory_store(request)
    brain = engine.brains.get(agent_id)

    recent_memories: list[AgentMemoryDTO] = []
    top_memories: list[AgentMemoryDTO] = []
    reflections: list[AgentMemoryDTO] = []
    relationships: list[AgentRelationshipDTO] = []

    if memory_store is not None:
        all_memories = await memory_store.list_memories(agent_id, limit=60)
        recent_memories = [_to_memory_dto(m) for m in all_memories[:20]]
        top_memories = [
            _to_memory_dto(m)
            for m in sorted(
                all_memories,
                key=lambda m: (m.importance, m.created_tick, m.id or 0),
                reverse=True,
            )[:8]
        ]
        reflection_records = [m for m in all_memories if m.type == "reflection"][:10]
        if len(all_memories) == 60:
            reflection_records = await memory_store.list_memories(
                agent_id,
                memory_type="reflection",
                limit=10,
            )
        reflections = [_to_memory_dto(m) for m in reflection_records]

        rels = await memory_store.list_relationships(agent_id)
        rels_by_peer: dict[str, AgentRelationshipDTO] = {}
        for rel in rels:
            peer_id = rel.agent_b if rel.agent_a == agent_id else rel.agent_a
            if peer_id == agent_id:
                continue
            existing = rels_by_peer.get(peer_id)
            if existing is not None and existing.last_interaction_tick > rel.last_interaction_tick:
                continue
            peer_agent = engine.agents.get(peer_id)
            peer_name = peer_agent.name if peer_agent is not None else peer_id
            rels_by_peer[peer_id] = AgentRelationshipDTO(
                peer_id=peer_id,
                peer_name=peer_name,
                affinity=rel.affinity,
                notes=rel.notes,
                last_interaction_tick=rel.last_interaction_tick,
            )
        relationships = sorted(
            rels_by_peer.values(),
            key=lambda item: (-abs(item.affinity), item.peer_name),
        )

    plan_state = brain.plan_state if brain is not None else None
    if plan_state is not None:
        raw_step = plan_state.current_step()
        current_step = (
            PlanStepDTO(
                duration_minutes=raw_step.duration_minutes,
                location=raw_step.location,
                action=raw_step.action,
                start_tick=raw_step.start_tick,
                end_tick=raw_step.end_tick,
                arrived=raw_step.arrived,
            )
            if raw_step is not None
            else None
        )
        daily_plan = [
            PlanBlockDTO(
                start_hour=block.start_hour,
                end_hour=block.end_hour,
                location=block.location,
                description=block.description,
                hourly_focus=plan_state.hourly_focus_by_block.get(idx),
                actions=[
                    PlanStepDTO(
                        duration_minutes=step.duration_minutes,
                        location=step.location,
                        action=step.action,
                        start_tick=step.start_tick,
                        end_tick=step.end_tick,
                        arrived=step.arrived,
                    )
                    for step in plan_state.minute_steps_by_block.get(idx, [])
                ],
            )
            for idx, block in enumerate(plan_state.daily_items)
        ]
        plan_dto = AgentPlanDTO(
            day=plan_state.day,
            active_block_index=plan_state.active_block_index,
            active_minute_index=plan_state.active_minute_index,
            hourly_focus=plan_state.hourly_focus_by_block.get(plan_state.active_block_index),
            current_step=current_step,
            daily_plan=daily_plan,
        )
    else:
        plan_dto = AgentPlanDTO(
            day=None,
            active_block_index=0,
            active_minute_index=0,
            hourly_focus=None,
            current_step=None,
            daily_plan=[
                PlanBlockDTO(
                    start_hour=6 + idx,
                    end_hour=7 + idx,
                    location=loc,
                    description=f"Routine visit to {loc}",
                )
                for idx, loc in enumerate(agent.routine[:18])
            ],
        )

    persona_dto = AgentPersonaDTO(
        id=agent.persona.id,
        name=agent.persona.name,
        age=agent.persona.age,
        role=agent.persona.role,
        traits=list(agent.persona.traits),
        bio=agent.persona.bio,
        home_location=agent.persona.home_location,
        starting_goals=list(agent.persona.starting_goals),
    )

    return AgentDetailResponse(
        id=agent.id,
        name=agent.name,
        role=agent.role,
        sprite_index=agent.sprite_index,
        x=agent.x,
        y=agent.y,
        home_location=agent.home_location,
        current_location=_resolve_agent_location_label(agent, world),
        target_location=agent.target_location,
        current_action=agent.current_action,
        mood=agent.mood,
        accumulated_importance=brain.accumulated_importance if brain is not None else 0,
        reflection_threshold=(
            brain.reflection_threshold if brain is not None else engine.reflection_threshold
        ),
        persona=persona_dto,
        plan=plan_dto,
        recent_memories=recent_memories,
        top_memories=top_memories,
        reflections=reflections,
        relationships=relationships,
    )


@router.get("/relationships", response_model=RelationshipsResponse)
async def get_relationships(request: Request) -> RelationshipsResponse:
    """Return agent nodes and canonical undirected pairwise relationship edges."""
    engine = _get_engine(request)
    memory_store = _get_memory_store(request)

    nodes = [
        RelationshipNodeDTO(
            id=agent.id,
            name=agent.name,
            role=agent.role,
            mood=agent.mood,
        )
        for agent in (engine.agents[agent_id] for agent_id in sorted(engine.agents))
    ]

    edges: list[RelationshipEdgeDTO] = []
    if memory_store is not None:
        rels = await memory_store.list_relationships()
        edges_by_pair: dict[tuple[str, str], RelationshipEdgeDTO] = {}
        for rel in rels:
            if rel.agent_a == rel.agent_b:
                continue
            canon_a, canon_b = (
                (rel.agent_a, rel.agent_b)
                if rel.agent_a < rel.agent_b
                else (rel.agent_b, rel.agent_a)
            )
            existing = edges_by_pair.get((canon_a, canon_b))
            if (
                existing is not None
                and existing.last_interaction_tick > rel.last_interaction_tick
            ):
                continue
            agent_a_entity = engine.agents.get(canon_a)
            agent_b_entity = engine.agents.get(canon_b)
            edges_by_pair[(canon_a, canon_b)] = RelationshipEdgeDTO(
                agent_a=canon_a,
                agent_b=canon_b,
                agent_a_name=agent_a_entity.name if agent_a_entity is not None else canon_a,
                agent_b_name=agent_b_entity.name if agent_b_entity is not None else canon_b,
                affinity=rel.affinity,
                notes=rel.notes,
                last_interaction_tick=rel.last_interaction_tick,
            )
        edges = [edges_by_pair[pair] for pair in sorted(edges_by_pair)]

    return RelationshipsResponse(nodes=nodes, edges=edges)


@router.post("/sim/start", response_model=SimControlResponse)
async def post_sim_start(request: Request) -> SimControlResponse:
    """Start or resume the live simulation loop and return current clock state."""
    engine = _get_engine(request)
    payload = await engine.start_simulation()
    return _to_sim_control_response(payload)


@router.post("/sim/pause", response_model=SimControlResponse)
async def post_sim_pause(request: Request) -> SimControlResponse:
    """Pause the live simulation loop and return current clock state."""
    engine = _get_engine(request)
    payload = await engine.pause_simulation()
    return _to_sim_control_response(payload)


@router.post("/sim/speed", response_model=SimControlResponse)
async def post_sim_speed(
    body: SimSpeedRequest,
    request: Request,
) -> SimControlResponse:
    """Set simulation playback speed (1, 4, or 16) and return current clock state."""
    engine = _get_engine(request)
    try:
        payload = await engine.set_simulation_speed(body.speed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_sim_control_response(payload)


@router.post("/events", response_model=InjectEventResponse)
async def post_event(
    payload: InjectEventRequest,
    request: Request,
) -> InjectEventResponse:
    """Inject a god-mode event globally or near a named village location."""
    clean_text = payload.text.strip()
    if not clean_text:
        raise HTTPException(status_code=422, detail="Event text must not be blank.")

    normalized_location = (
        payload.location.strip()
        if payload.location and payload.location.strip()
        else None
    )
    engine = _get_engine(request)
    try:
        result = await engine.inject_event(clean_text, location=normalized_location)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return InjectEventResponse(**result)


@router.get("/metrics", response_model=MetricsSnapshot)
async def get_metrics(request: Request) -> MetricsSnapshot:
    """Return aggregated LLM call telemetry, budget usage, and rolling per-tick history."""
    engine = _get_engine(request)
    gateway = _get_llm_gateway(request)
    if gateway is not None:
        return await gateway.get_metrics_snapshot(
            tick=engine.clock.tick,
            sim_time=engine.clock.sim_time_str,
            day=engine.clock.day,
        )
    return MetricsSnapshot(
        tick=engine.clock.tick,
        sim_time=engine.clock.sim_time_str,
        day=engine.clock.day,
        total_calls=0,
        cache_hits=0,
        cache_hit_rate=0.0,
        tokens_in=0,
        tokens_out=0,
        total_tokens=0,
        cost_est=0.0,
        avg_latency_ms=0.0,
        max_latency_ms=0.0,
        daily_budget_usd=0.0,
        daily_token_limit=0,
        budget_day=1,
        budget_tokens_used=0,
        budget_cost_used=0.0,
        by_purpose=[],
        by_model=[],
        history=[],
    )


@router.get("/replay", response_model=ReplayDaysResponse)
async def get_replay_days(request: Request) -> ReplayDaysResponse:
    """List recorded simulation replay days with tick bounds."""
    engine = _get_engine(request)
    replay_logger = _get_replay_logger(request)
    days = await replay_logger.list_days() if replay_logger is not None else []
    return ReplayDaysResponse(current_day=engine.clock.day, days=days)


@router.get("/replay/{day}", response_model=ReplayDayLog)
async def get_replay_day(
    day: Annotated[int, FastAPIPath(ge=1)],
    request: Request,
) -> ReplayDayLog:
    """Return parsed JSONL replay frames for a 1-indexed simulated day."""
    replay_logger = _get_replay_logger(request)
    day_log = await replay_logger.read_day(day) if replay_logger is not None else None
    if day_log is None:
        raise HTTPException(
            status_code=404,
            detail=f"Replay log for day {day} not found.",
        )
    return day_log
