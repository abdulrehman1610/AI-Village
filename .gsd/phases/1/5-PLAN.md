---
phase: 1
plan: 5
wave: 3
depends_on:
  - "3"
  - "4"
files_modified:
  - backend/sim/engine.py
  - backend/api/ws.py
  - backend/api/rest.py
  - backend/app/main.py
  - backend/tests/test_engine.py
  - backend/tests/test_api_ws.py
autonomous: true
gap_closure: false
must_haves:
  truths:
    - "SimulationEngine moves 4 seeded agents between named locations using custom A* without wall clipping or tile overlap"
    - "Async tick loop runs non-blockingly and broadcasts structured tick state payloads to all connected /ws WebSocket clients"
    - "REST endpoints GET /health, GET /world, and GET /agents expose authoritative server state"
  artifacts:
    - "backend/sim/engine.py defines AgentEntity, TickPayload, and SimulationEngine with spatial invariants"
    - "backend/api/ws.py defines ConnectionManager and WebSocket /ws endpoint sending initial snapshot and live tick updates"
    - "backend/api/rest.py defines GET /health, GET /world, and GET /agents"
    - "backend/app/main.py creates FastAPI app with CORS, lifespan startup/shutdown of SimulationEngine, and routers"
    - "backend/tests/test_engine.py verifies A* routing between named locations and 150-tick zero-overlap / zero-wall-clipping invariants"
    - "backend/tests/test_api_ws.py verifies REST endpoints and WebSocket /ws initial + advancing tick payloads"
  key_links:
    - "backend/sim/engine.py wires WorldMap, SimClock, and astar.find_path together"
    - "backend/app/main.py connects engine tick callback to ws_manager.broadcast_json"
---

# Plan 1.5: Async Simulation Engine, Multi-Agent Navigation & WebSocket `/ws`

## Objective
Build the server-authoritative `SimulationEngine` connecting `WorldMap`, `SimClock`, and `astar.find_path` to animate 4 moving villager agents across named locations under strict spatial invariants, and expose the FastAPI REST endpoints (`/health`, `/world`, `/agents`) and live WebSocket `/ws` broadcast server with full offline unit/integration tests.

## Context
Load these files for context:
- .gsd/SPEC.md
- .gsd/ARCHITECTURE.md
- .gsd/REQUIREMENTS.md
- backend/app/config.py
- backend/sim/world.py
- backend/sim/astar.py
- backend/sim/clock.py

## Tasks

<task type="auto">
  <name>Implement SimulationEngine with 4 seeded agents and spatial invariants</name>
  <files>
    backend/sim/engine.py
  </files>
  <action>
    Implement `backend/sim/engine.py` coordinating the async simulation tick loop, A* goal navigation between named locations, and non-overlapping tile movement.

    Steps:
    1. Define Pydantic v2 schemas:
       - `AgentSnapshot(BaseModel)`: `id: str`, `name: str`, `role: str`, `sprite_index: int`, `x: int`, `y: int`, `target_location: str | None`, `current_action: str`.
       - `TickPayload(BaseModel)`: `type: Literal["tick"] = "tick"`, `tick: int`, `sim_time: str`, `day: int`, `speed: int`, `running: bool`, `agents: list[AgentSnapshot]`.
    2. Define runtime dataclass `AgentEntity` holding `id`, `name`, `role`, `sprite_index`, `home_location`, `x`, `y`, `target_location`, `path: list[GridPos]`, `current_action`, `dwell_ticks_remaining: int`, `stall_ticks: int`, `routine: list[str]`, `routine_index: int`, `visited_locations: set[str]`.
    3. Seed 4 distinct initial agents in `_create_initial_agents(world: WorldMap)` (with distinct `sprite_index` `0..3` matching `sprites.png` rows, starting at their distinct `Home_*` anchors so initial positions are guaranteed non-overlapping):
       - `maya` ("Maya", "Baker", sprite 0, home `Home_Maya`, routine `["Bakery", "Cafe", "Market", "Town Square", "Home_Maya"]`)
       - `liam` ("Liam", "Barista", sprite 1, home `Home_Liam`, routine `["Cafe", "Town Square", "Park", "Market", "Home_Liam"]`)
       - `elena` ("Elena", "Botanist", sprite 2, home `Home_Elena`, routine `["Park", "Library", "Cafe", "Town Square", "Home_Elena"]`)
       - `noah` ("Noah", "Merchant", sprite 3, home `Home_Noah`, routine `["Market", "Town Square", "Bakery", "Park", "Home_Noah"]`)
    4. Implement `SimulationEngine`:
       - `__init__(self, world: WorldMap, clock: SimClock | None = None, seed: int = 42, dwell_ticks: int = 4)` with `asyncio.Lock` (`_step_lock`) and `_tick_callbacks: list[Callable[[TickPayload], Awaitable[None]]]`.
       - `register_tick_callback(cb)` and `build_tick_payload() -> TickPayload`.
       - `async def step_once(self) -> TickPayload`: under `self._step_lock`:
         - Maintain `reserved_tiles: set[GridPos] = {(a.x, a.y) for a in self.agents.values()}`.
         - Iterate agents in sorted/deterministic order:
           a. If `agent.dwell_ticks_remaining > 0`: decrement, keep `current_action = f"At {agent.target_location}"`, continue.
           b. If `agent.target_location is None` or `not agent.path` while not dwelling: advance `routine_index = (routine_index + 1) % len(routine)` (skipping current position's location if already there), set `target_location`, resolve target anchor `goal = world.get_location(target_location).anchor`. If `goal` is occupied (`goal in reserved_tiles` and `(agent.x, agent.y) != goal`), pick `world.find_free_adjacent(goal[0], goal[1], reserved_tiles, max_radius=3)` as effective goal; compute `agent.path = find_path((agent.x, agent.y), effective_goal, world.is_walkable, blocked_tiles=reserved_tiles - {(agent.x, agent.y)}) or []`.
           c. If `agent.path` is non-empty: peek `next_pos = agent.path[0]`. If `world.is_walkable(*next_pos)` and `next_pos not in reserved_tiles`:
              - Move: remove `(agent.x, agent.y)` from `reserved_tiles`, set `agent.x, agent.y = next_pos`, add `next_pos` to `reserved_tiles`, pop `agent.path[0]`, set `current_action = f"Walking to {agent.target_location}"`.
              - If `not agent.path`: arrived! Set `dwell_ticks_remaining = self.dwell_ticks`, record `target_location` in `visited_locations`, set `current_action = f"At {agent.target_location}"`, reset `agent.stall_ticks = 0`.
              Else (next tile occupied by another agent): increment `agent.stall_ticks` and recompute path avoiding `reserved_tiles - {(agent.x, agent.y)}` toward goal (or free adjacent tile near goal); if a detour step is available and unreserved, take it or wait 1 tick cleanly (never overwrite an occupied tile!). If `agent.stall_ticks > 15`, clear `agent.path` and advance to the next routine destination so agents never deadlock.
         - Advance `self.clock.advance()` and return `payload = self.build_tick_payload()`.
         - After releasing lock (or before returning), invoke registered async tick callbacks safely (catching/logging errors per callback).
       - `async def start_loop(self) -> None`, `async def stop_loop(self) -> None`, and `_run_loop(self) -> None` sleeping `self.clock.tick_interval_seconds` per iteration and stepping only when `self.clock.running` is True (sleeping `0.1s` when paused).

    AVOID: Letting two agents share a tile at tick end or allowing an agent to step onto a tile with `world.is_walkable(...) == False`.
    USE: `reserved_tiles` updated atomically per agent step inside `step_once()` so the zero-overlap invariant holds unconditionally.
  </action>
  <verify>
    uv --directory backend run ruff check sim/engine.py
    uv --directory backend run mypy sim/engine.py
  </verify>
  <done>
    `backend/sim/engine.py` passes `ruff check` and strict `mypy` with zero errors.
  </done>
</task>

<task type="auto">
  <name>Implement WebSocket /ws manager, REST endpoints, and FastAPI app</name>
  <files>
    backend/api/ws.py
    backend/api/rest.py
    backend/app/main.py
  </files>
  <action>
    Implement the FastAPI WebSocket manager, REST inspection endpoints, and main FastAPI application lifespan.

    Steps:
    1. In `backend/api/ws.py`:
       - Implement `ConnectionManager` storing `active_connections: set[WebSocket]`, `async def connect(ws: WebSocket) -> None`, `def disconnect(ws: WebSocket) -> None`, `async def broadcast_json(payload: dict[str, Any]) -> None` (iterating over `list(self.active_connections)` and catching `(WebSocketDisconnect, RuntimeError, OSError)` per client to prune closed sockets cleanly).
       - Define `router = APIRouter()` with `@router.websocket("/ws")` endpoint:
         - Retrieves `engine: SimulationEngine = websocket.app.state.engine` and `manager: ConnectionManager = websocket.app.state.ws_manager`.
         - Connects, immediately sends `engine.build_tick_payload().model_dump()`, then awaits incoming client messages (`await websocket.receive_text()`) in a `try/except WebSocketDisconnect` loop so disconnects clean up promptly.
    2. In `backend/api/rest.py`:
       - Define `router = APIRouter()` exposing:
         - `GET /health`: returns `{"status": "ok", "tick": engine.clock.tick, "sim_time": engine.clock.sim_time_str, "agents": len(engine.agents), "map_width": engine.world.width, "map_height": engine.world.height}`.
         - `GET /world`: returns `{"width": world.width, "height": world.height, "tile_size": world.tile_size, "locations": [loc.model_dump() for loc in world.list_locations()]}` (using Pydantic response model or serializable dicts).
         - `GET /agents`: returns `[a.model_dump() for a in engine.build_tick_payload().agents]`.
    3. In `backend/app/main.py`:
       - Implement `create_app(settings: Settings | None = None) -> FastAPI`:
         - Resolves settings via `settings or get_settings()`.
         - Configures `@asynccontextmanager async def lifespan(app: FastAPI)`:
           - Loads `world = WorldMap.from_tiled_json(resolved_settings.resolved_map_path())`.
           - Creates `clock = SimClock(speed=resolved_settings.sim_speed, base_tick_seconds=resolved_settings.sim_tick_seconds)`.
           - Creates `engine = SimulationEngine(world=world, clock=clock, seed=resolved_settings.sim_seed)`.
           - Creates `ws_manager = ConnectionManager()` and registers `async def _broadcast(payload: TickPayload) -> None: await ws_manager.broadcast_json(payload.model_dump())`.
           - Attaches `world`, `clock`, `engine`, `ws_manager` to `app.state`.
           - If `resolved_settings.sim_auto_start`: calls `await engine.start_loop()`.
           - On shutdown (`yield` cleanup): calls `await engine.stop_loop()`.
         - Adds `CORSMiddleware` with `allow_origins=resolved_settings.parsed_cors_origins()`, `allow_methods=["*"]`, `allow_headers=["*"]`.
         - Includes `rest.router` and `ws.router`.
       - Instantiate module-level `app = create_app()` for Uvicorn (`uvicorn app.main:app`).

    AVOID: Blocking the FastAPI startup or WebSocket broadcast loop if a browser tab closes mid-tick.
    USE: `create_app(settings=...)` factory pattern so tests can inject fast tick speeds or `sim_auto_start=False` cleanly.
  </action>
  <verify>
    uv --directory backend run ruff check api/ws.py api/rest.py app/main.py
    uv --directory backend run mypy api/ws.py api/rest.py app/main.py
  </verify>
  <done>
    `backend/api/ws.py`, `backend/api/rest.py`, and `backend/app/main.py` pass `ruff` and strict `mypy` with zero errors.
  </done>
</task>

<task type="auto">
  <name>Write offline engine invariant tests (including named-location A*) and WebSocket/REST API tests</name>
  <files>
    backend/tests/test_engine.py
    backend/tests/test_api_ws.py
  </files>
  <action>
    Write comprehensive offline tests for `SimulationEngine`, real named-location A* pathfinding, spatial invariants, REST endpoints, and WebSocket `/ws`.

    Steps:
    1. Create `backend/tests/test_engine.py`:
       - `test_astar_between_all_named_locations`: load real `map.json` via `WorldMap.from_tiled_json`, run `find_path` between `Cafe -> Park`, `Park -> Market`, `Market -> Town Square`, `Town Square -> Bakery`, `Bakery -> Library`, and `Home_Maya -> Cafe`, asserting non-`None` optimal paths where every tile satisfies `world.is_walkable(x, y)`.
       - `test_engine_150_ticks_spatial_invariants`: instantiate `SimulationEngine(world)` with 4 agents and step 150 ticks (`await engine.step_once()`):
         - Assert at EVERY tick: `len({(a.x, a.y) for a in engine.agents.values()}) == len(engine.agents)` (zero tile overlap).
         - Assert at EVERY tick: every agent position `(a.x, a.y)` satisfies `world.is_walkable(a.x, a.y)` (zero wall clipping).
         - Assert after 150 ticks: each of the 4 agents has moved from its initial position and visited at least 2 distinct named locations.
    2. Create `backend/tests/test_api_ws.py`:
       - Use `create_app(Settings(sim_auto_start=False, sim_tick_seconds=0.05))` with FastAPI `TestClient(app)` (inside `with TestClient(app) as client:` so lifespan runs!).
       - Test `GET /health` returns HTTP 200 with `status == "ok"`, `agents == 4`, `map_width == 40`, `map_height == 30`.
       - Test `GET /world` returns HTTP 200 with all 10 named locations including `Cafe`, `Park`, `Market`.
       - Test `GET /agents` returns HTTP 200 with 4 agents containing `id`, `name`, `x`, `y`, `sprite_index`.
       - Test WebSocket `/ws`: `with client.websocket_connect("/ws") as ws:` receives initial `"tick"` JSON message with 4 agents, then test live advancing ticks (using `create_app(Settings(sim_auto_start=True, sim_tick_seconds=0.05))`) confirming `/ws` receives advancing `tick` numbers (`msg2["tick"] > msg1["tick"]`) and moving agent coordinates!

    AVOID: Slow wall-clock sleeps (`>0.5s`) or external network requests in tests.
    USE: `sim_tick_seconds=0.05` for the live WebSocket broadcast test and direct `await engine.step_once()` for the 150-tick invariant test so the entire suite completes in under 2 seconds.
  </action>
  <verify>
    uv --directory backend run pytest -v
    uv --directory backend run ruff check .
    uv --directory backend run mypy app sim api tests
  </verify>
  <done>
    All tests across `test_config.py`, `test_world.py`, `test_astar.py`, `test_clock.py`, `test_engine.py`, and `test_api_ws.py` pass offline with 0 failures, and `ruff` + `mypy` exit 0.
  </done>
</task>

## Must-Haves
After all tasks complete, verify:
- [ ] 4 seeded agents route between real named locations (`Cafe`, `Park`, `Market`, `Town Square`, `Bakery`, `Library`, `Home_*`) via custom `heapq` A*
- [ ] Over 150 simulated ticks, zero wall collisions and zero agent tile overlaps occur
- [ ] FastAPI server exposes `/health`, `/world`, `/agents`, and WebSocket `/ws` streaming initial snapshot and real-time ticks

## Success Criteria
- [ ] All tasks verified passing
- [ ] Must-haves confirmed
- [ ] No regressions in tests
