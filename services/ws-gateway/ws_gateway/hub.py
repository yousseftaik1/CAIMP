from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket
from prometheus_client import Gauge

log = logging.getLogger(__name__)

_active_connections = Gauge(
    "ws_gateway_active_connections",
    "Active WebSocket connections",
    ["org_id"],
)


class ConnectionHub:
    """Thread-safe registry of active WebSocket connections, keyed by org_id."""

    def __init__(self) -> None:
        self._conns: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, org_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._conns[org_id].add(ws)
        _active_connections.labels(org_id=org_id).set(len(self._conns[org_id]))

    async def disconnect(self, org_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._conns[org_id].discard(ws)
            if not self._conns[org_id]:
                del self._conns[org_id]
        _active_connections.labels(org_id=org_id).set(len(self._conns.get(org_id, set())))

    async def broadcast(self, org_id: str, payload: dict) -> None:
        """Send JSON payload to every WebSocket in the org. Remove dead connections."""
        data = json.dumps(payload, default=str)
        async with self._lock:
            conns = set(self._conns.get(org_id, set()))

        dead: set[WebSocket] = set()
        for ws in conns:
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)

        if dead:
            async with self._lock:
                self._conns[org_id] -= dead

    def total_connections(self) -> int:
        return sum(len(v) for v in self._conns.values())


hub = ConnectionHub()
