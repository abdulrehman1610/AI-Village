"""FastAPI application factory and lifespan orchestration for AI Village."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import rest, ws
from api.ws import ConnectionManager
from app.config import Settings, get_settings
from app.db import Database
from llm.gateway import LLMGateway
from llm.providers.base import LLMProvider
from llm.providers.gemini import GeminiProvider
from llm.providers.mock import MockProvider
from memory.embeddings import EmbeddingService
from memory.retrieval import MemoryRetriever
from memory.store import MemoryStore
from sim.clock import SimClock
from sim.engine import SimulationEngine, TickPayload
from sim.replay import ReplayLogger
from sim.world import WorldMap


def _build_llm_provider(settings: Settings) -> LLMProvider:
    """Instantiate the configured primary LLM provider from application settings."""
    mode = settings.llm_provider.strip().lower()
    if mode == "mock":
        return MockProvider(seed=settings.sim_seed)
    if mode == "gemini":
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            default_model=settings.gemini_routine_model,
        )
    raise ValueError(f"Unsupported llm_provider: {settings.llm_provider!r}")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct and configure the FastAPI app with lifespan-managed SimulationEngine."""
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(resolved_settings.resolved_database_url())
        engine: SimulationEngine | None = None

        try:
            await db.init_models()
            embedding_service = EmbeddingService.from_mode(
                resolved_settings.resolved_embedding_provider()
            )
            memory_store = MemoryStore(db=db, embedding_service=embedding_service)
            memory_retriever = MemoryRetriever(
                store=memory_store,
                embedding_service=embedding_service,
                w_recency=resolved_settings.retrieval_w_recency,
                w_importance=resolved_settings.retrieval_w_importance,
                w_relevance=resolved_settings.retrieval_w_relevance,
                decay_per_hour=resolved_settings.retrieval_decay_per_hour,
                default_top_k=resolved_settings.retrieval_top_k,
            )
            llm_gateway = LLMGateway(
                provider=_build_llm_provider(resolved_settings),
                fallback_provider=MockProvider(seed=resolved_settings.sim_seed),
                db=db,
                daily_budget_usd=resolved_settings.llm_daily_budget_usd,
                daily_token_limit=resolved_settings.llm_daily_token_limit,
                max_retries=resolved_settings.llm_max_retries,
                routine_model=resolved_settings.gemini_routine_model,
                planning_model=resolved_settings.gemini_planning_model,
                seed=resolved_settings.sim_seed,
            )

            world = WorldMap.from_tiled_json(resolved_settings.resolved_map_path())
            clock = SimClock(
                speed=resolved_settings.sim_speed,
                running=resolved_settings.sim_auto_start,
                base_tick_seconds=resolved_settings.sim_tick_seconds,
            )
            replay_logger = ReplayLogger(
                resolved_settings.resolved_replay_log_dir(),
                start_minute_of_day=clock.start_minute_of_day,
            )
            engine = SimulationEngine(
                world=world,
                clock=clock,
                seed=resolved_settings.sim_seed,
                memory_store=memory_store,
                retriever=memory_retriever,
                llm_gateway=llm_gateway,
                replay_logger=replay_logger,
                reflection_threshold=resolved_settings.reflection_threshold,
            )
            await engine.initialize_persistence()
            ws_manager = ConnectionManager()

            async def _broadcast(payload: TickPayload) -> None:
                await ws_manager.broadcast_json(payload.model_dump())

            async def _broadcast_event(payload: dict[str, Any]) -> None:
                await ws_manager.broadcast_json(payload)

            engine.register_tick_callback(_broadcast)
            engine.register_event_callback(_broadcast_event)

            app.state.settings = resolved_settings
            app.state.db = db
            app.state.embedding_service = embedding_service
            app.state.memory_store = memory_store
            app.state.memory_retriever = memory_retriever
            app.state.llm_gateway = llm_gateway
            app.state.world = world
            app.state.clock = clock
            app.state.engine = engine
            app.state.replay_logger = replay_logger
            app.state.ws_manager = ws_manager

            if resolved_settings.sim_auto_start:
                await engine.start_loop()
            yield
        finally:
            try:
                if engine is not None:
                    await engine.stop_loop()
            finally:
                await db.dispose()

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
