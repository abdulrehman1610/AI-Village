# Architecture Decision Records (DECISIONS.md)

## ADR-001: v1.0 Milestone Scope (P0 + P1 across 6 Phases)
- **Date**: 2026-11-23
- **Status**: Accepted
- **Context**: The PRD defines P0 (MVP features F1–F8), P1 (Impressive features F9–F14), and P2 (Stretch features F15–F17) across a 6-milestone structure.
- **Decision**: Scope v1.0 to cover all P0 and P1 features (F1–F14) plus full packaging, CI, and the AI Lab Report across 6 sequential phases.
- **Consequences**: Delivers both the required course lab concepts and the impressive portfolio features (reflections, relationship graph, inspector, time controls, replay, cost dashboard) without scope creep from P2 before the core simulation is solid.

## ADR-002: Server-Authoritative Simulation & Single LLM Gateway
- **Date**: 2026-11-23
- **Status**: Accepted
- **Context**: Multi-agent simulations can easily desynchronize if the frontend computes movement, or exceed API budgets if agents call LLMs directly on ticks.
- **Decision**: The FastAPI simulation engine owns 100% of world state and pathfinding; Phaser 3 only renders server state. All LLM calls go exclusively through `backend/llm/gateway.py` with strict Pydantic v2 validation, caching, budget limits, and a deterministic `MockProvider` for offline testing.
- **Consequences**: Reproducible tests with zero API keys required, predictable LLM costs, and clean separation between simulation logic and visualization.
