"""FastAPI application factory and lifespan orchestration for AI Village."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import rest, ws
from api.ws import ConnectionManager
from app.config import Settings, get_settings
from sim.clock import SimClock
from sim.engine import SimulationEngine, TickPayload
from sim.world import WorldMap


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct and configure the FastAPI app with lifespan-managed SimulationEngine."""
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        world = WorldMap.from_tiled_json(resolved_settings.resolved_map_path())
        clock = SimClock(
            speed=resolved_settings.sim_speed,
            base_tick_seconds=resolved_settings.sim_tick_seconds,
        )
        engine = SimulationEngine(
            world=world,
            clock=clock,
            seed=resolved_settings.sim_seed,
        )
        ws_manager = ConnectionManager()

        async def _broadcast(payload: TickPayload) -> None:
            await ws_manager.broadcast_json(payload.model_dump())

        engine.register_tick_callback(_broadcast)

        app.state.settings = resolved_settings
        app.state.world = world
        app.state.clock = clock
        app.state.engine = engine
        app.state.ws_manager = ws_manager

        if resolved_settings.sim_auto_start:
            await engine.start_loop()
        try:
            yield
        finally:
            await engine.stop_loop()

    application = FastAPI(title="AI Village API", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.parsed_cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(rest.router)
    application.include_router(ws.router)
    return application


app = create_app()
