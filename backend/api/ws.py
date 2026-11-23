"""WebSocket connection manager and live simulation /ws endpoint."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from sim.engine import SimulationEngine

router = APIRouter()


class ConnectionManager:
    """Tracks active WebSocket clients and broadcasts JSON payloads safely."""

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept an incoming WebSocket connection and register it."""
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection if present."""
        self.active_connections.discard(websocket)

    async def broadcast_json(self, payload: dict[str, Any]) -> None:
        """Broadcast a JSON payload to all connected clients, pruning closed sockets."""
        for websocket in list(self.active_connections):
            try:
                await websocket.send_json(payload)
            except (WebSocketDisconnect, RuntimeError, OSError):
                self.disconnect(websocket)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Send initial simulation snapshot and keep socket open for live tick broadcasts."""
    engine = cast(SimulationEngine, websocket.app.state.engine)
    manager = cast(ConnectionManager, websocket.app.state.ws_manager)

    await manager.connect(websocket)
    try:
        await websocket.send_json(engine.build_tick_payload().model_dump())
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass
    finally:
        manager.disconnect(websocket)
