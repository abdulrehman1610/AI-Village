"""Offline validation tests for AgentPersona definitions and Tiled map alignment."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.personas import SEEDED_PERSONA_BY_ID, SEEDED_PERSONAS, AgentPersona, get_persona
from app.config import get_settings
from sim.world import WorldMap


def test_seeded_personas_count_and_uniqueness() -> None:
    assert 6 <= len(SEEDED_PERSONAS) <= 10
    assert len(SEEDED_PERSONAS) == 8

    ids = [persona.id for persona in SEEDED_PERSONAS]
    names = [persona.name for persona in SEEDED_PERSONAS]
    sprite_indices = [persona.sprite_index for persona in SEEDED_PERSONAS]

    assert len(set(ids)) == len(SEEDED_PERSONAS)
    assert len(set(names)) == len(SEEDED_PERSONAS)
    assert sprite_indices == list(range(8))
    assert set(SEEDED_PERSONA_BY_ID.keys()) == set(ids)


def test_seeded_personas_content_json_roundtrip_and_lookup() -> None:
    for persona in SEEDED_PERSONAS:
        assert 18 <= persona.age <= 100
        assert len(persona.traits) >= 3
        assert all(trait.strip() for trait in persona.traits)
        assert len(persona.starting_goals) >= 2
        assert all(goal.strip() for goal in persona.starting_goals)
        assert len(persona.default_routine) >= 3
        assert len(persona.bio.strip()) >= 10

        raw_json = persona.to_persona_json()
        rehydrated = AgentPersona.model_validate_json(raw_json)
        assert rehydrated == persona

        summary = persona.summary_text()
        assert persona.name in summary
        assert persona.role in summary
        assert persona.home_location in summary

        assert get_persona(persona.id) == persona

    with pytest.raises(KeyError):
        get_persona("nonexistent-villager")


def test_agent_persona_is_frozen_and_validates_constraints() -> None:
    maya = get_persona("maya")
    with pytest.raises(ValidationError):
        maya.role = "Blacksmith"

    with pytest.raises(ValidationError):
        AgentPersona(
            id="bad",
            name="Bad",
            age=12,
            role="Child",
            traits=("a", "b"),
            bio="too short",
            home_location="Cafe",
            starting_goals=("only one",),
            default_routine=("Cafe", "Park"),
            sprite_index=-1,
        )


def test_seeded_personas_map_only_to_valid_walkable_locations() -> None:
    world = WorldMap.from_tiled_json(get_settings().resolved_map_path())
    town_square = world.get_location("Town Square")
    reachable = world.reachable_from(town_square.anchor)

    for persona in SEEDED_PERSONAS:
        home = world.get_location(persona.home_location)
        assert world.is_walkable(*home.anchor), f"{persona.id} home {home.name} is not walkable"
        assert home.anchor in reachable, f"{persona.id} home {home.name} is not reachable"

        for destination in persona.default_routine:
            loc = world.get_location(destination)
            assert world.is_walkable(*loc.anchor), (
                f"{persona.id} routine stop {destination} is not walkable"
            )
            assert loc.anchor in reachable, (
                f"{persona.id} routine stop {destination} is not reachable"
            )
