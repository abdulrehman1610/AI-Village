---
phase: 2
plan: 4
completed_at: 2026-11-24T12:22:15+05:00
duration_minutes: 8
---

# Summary: Plan 2.4 — 8 Rich Agent Personas & Expanded 8-Row Villager Spritesheet

## Results
- 2 tasks completed atomically
- All verifications (`pytest`, `ruff check`, `mypy` strict, PNG dimension check, `map.json` zero-diff check, `tsc --noEmit`, `vite build`) passed with zero errors

## Tasks Completed
| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Create AgentPersona model, 8 seeded personas, and offline persona validation tests | `f1aba6e` | ✅ |
| 2 | Expand spritesheet generator to 8 character rows and add defensive wrapping in VillageScene.ts | `72284b5` | ✅ |

## Deviations Applied
None — executed as planned.

## Files Changed
- `backend/agents/__init__.py` - Created package docstring for autonomous villager personas and cognitive loop components.
- `backend/agents/personas.py` - Defined frozen `AgentPersona` Pydantic v2 model (`to_persona_json()`, `summary_text()`), 8 `SEEDED_PERSONAS` (`maya`, `liam`, `elena`, `noah`, `clara`, `marcus`, `aria`, `sam` with `sprite_index` `0..7` mapped exclusively to existing Tiled locations), `SEEDED_PERSONA_BY_ID`, and `get_persona()`.
- `backend/tests/test_personas.py` - Added 4 offline tests validating persona count (`8`, within `6..10`), uniqueness, sprite indices `0..7`, traits/goals/bio constraints, JSON roundtrip, immutability, `get_persona()` lookup, and walkable/reachable Tiled map anchors for all homes and routine stops.
- `scripts/generate_village_map.py` - Updated `SPRITE_ROWS = 8` (`128x256` RGBA spritesheet, 32 frames), extended `palettes` to 8 distinct villager color schemes with `assert len(palettes) == SPRITE_ROWS`, and left `tileset.png` and `map.json` generation untouched.
- `frontend/public/assets/sprites.png` - Regenerated `128x256` RGBA spritesheet containing 8 villager rows x 4 walking poses.
- `frontend/src/scenes/VillageScene.ts` - Added defensive row wrapping in `syncAgentVisual()` using `this.textures.get("villagers").getFrameNames().length` divided by `FRAMES_PER_AGENT` (`4`).

## Verification
- `pytest -v tests/test_personas.py` (in `backend/`): ✅ `4 passed in 0.53s`
- `ruff check agents/__init__.py agents/personas.py tests/test_personas.py` (in `backend/`): ✅ `All checks passed!`
- `mypy agents/__init__.py agents/personas.py tests/test_personas.py` (in `backend/`): ✅ `Success: no issues found in 3 source files`
- `backend\.venv\Scripts\python.exe scripts\generate_village_map.py`: ✅ Regenerated assets cleanly
- PNG header check (`frontend/public/assets/sprites.png` and `frontend/dist/assets/sprites.png`): ✅ `128 256`
- `git diff -- frontend/public/assets/map.json frontend/public/assets/tileset.png`: ✅ Zero diff (unchanged)
- `ruff check --config backend\pyproject.toml scripts\generate_village_map.py`: ✅ `All checks passed!`
- `mypy --config-file backend\pyproject.toml scripts\generate_village_map.py`: ✅ `Success: no issues found in 1 source file`
- `npm --prefix frontend run typecheck`: ✅ `tsc --noEmit` exited 0
- `npm --prefix frontend run build`: ✅ `vite build` succeeded (`built in 30.22s`)
- Full backend regression checks (in `backend/`): ✅ `pytest -q` (`65 passed in 7.62s`), `ruff check .` (`All checks passed!`), `mypy .` (`Success: no issues found in 38 source files`)

## Deferred
None.
