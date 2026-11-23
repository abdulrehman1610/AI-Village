"""Offline integration tests for REST endpoints and WebSocket /ws live broadcasts."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

EXPECTED_LOCATION_NAMES = {
    "Cafe",
    "Park",
    "Market",
    "Town Square",
    "Bakery",
    "Library",
    "Home_Maya",
    "Home_Liam",
    "Home_Elena",
    "Home_Noah",
}


def test_rest_endpoints_and_initial_websocket_snapshot() -> None:
    app = create_app(Settings(sim_auto_start=False, sim_tick_seconds=0.05))

    with TestClient(app) as client:
        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        assert health_data["status"] == "ok"
        assert health_data["agents"] == 4
        assert health_data["map_width"] == 40
        assert health_data["map_height"] == 30
        assert health_data["tick"] == 0

        world_resp = client.get("/world")
        assert world_resp.status_code == 200
        world_data = world_resp.json()
        assert world_data["width"] == 40
        assert world_data["height"] == 30
        assert world_data["tile_size"] == 32
        location_names = {loc["name"] for loc in world_data["locations"]}
        assert location_names == EXPECTED_LOCATION_NAMES

        agents_resp = client.get("/agents")
        assert agents_resp.status_code == 200
        agents_data = agents_resp.json()
        assert len(agents_data) == 4
        assert {agent["sprite_index"] for agent in agents_data} == {0, 1, 2, 3}
        for agent in agents_data:
            assert {"id", "name", "role", "sprite_index", "x", "y", "current_action"} <= set(
                agent.keys()
            )

        with client.websocket_connect("/ws") as ws:
            initial_msg = ws.receive_json()
            assert initial_msg["type"] == "tick"
            assert initial_msg["tick"] == 0
            assert len(initial_msg["agents"]) == 4


def test_websocket_streams_advancing_ticks_and_moving_agents() -> None:
    app = create_app(Settings(sim_auto_start=True, sim_tick_seconds=0.05))

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            msg1 = ws.receive_json()
            msg2 = ws.receive_json()
            assert msg1["type"] == "tick"
            assert msg2["type"] == "tick"
            assert msg2["tick"] > msg1["tick"]

            coords1 = {(a["id"], a["x"], a["y"]) for a in msg1["agents"]}
            coords2 = {(a["id"], a["x"], a["y"]) for a in msg2["agents"]}
            assert coords1 != coords2
