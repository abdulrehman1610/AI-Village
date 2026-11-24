"""REST API endpoints exposing authoritative village health, world, and agent state."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from sim.engine import AgentSnapshot, SimulationEngine
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


def _get_engine(request: Request) -> SimulationEngine:
    return cast(SimulationEngine, request.app.state.engine)


def _get_world(request: Request) -> WorldMap:
    return cast(WorldMap, request.app.state.world)


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
