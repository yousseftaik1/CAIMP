from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import jwt as pyjwt
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from prometheus_client import make_asgi_app

from nats_client.client import NatsClient

from .config import settings
from .hub import hub
from .nats_fanout import start_fanout

log = logging.getLogger(__name__)
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_nats_client: NatsClient | None = None
_nats_ctx = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _nats_client, _nats_ctx
    _nats_ctx = NatsClient.connect(
        url=settings.nats_url,
        user=settings.nats_user,
        password=settings.nats_password,
    )
    _nats_client = await _nats_ctx.__aenter__()
    await start_fanout(_nats_client)
    log.info("WS Gateway started")
    yield
    await _nats_ctx.__aexit__(None, None, None)
    log.info("WS Gateway stopped")


app = FastAPI(title="CAIMP WS Gateway", version="2.0.0", lifespan=lifespan)

# Prometheus metrics endpoint
app.mount("/metrics", make_asgi_app())


def _validate_token(token: str) -> dict | None:
    try:
        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return payload
    except pyjwt.PyJWTError:
        return None


@app.websocket("/ws/{org_id}")
async def ws_endpoint(
    ws: WebSocket,
    org_id: str,
    token: str = Query(...),
):
    payload = _validate_token(token)
    if not payload:
        await ws.close(code=4001, reason="Invalid token")
        return

    # Agents and users of other orgs cannot connect to this org's channel
    token_org = payload.get("org_id", "")
    role = payload.get("role", "viewer")
    if role != "admin" and token_org != org_id:
        await ws.close(code=4003, reason="Forbidden")
        return

    await ws.accept()
    await hub.connect(org_id, ws)
    log.info("WS connected org=%s total=%d", org_id, hub.total_connections())

    try:
        # Keep alive — receive any client pings/messages and discard
        while True:
            await asyncio.wait_for(ws.receive_text(), timeout=30)
    except (WebSocketDisconnect, asyncio.TimeoutError, Exception):
        pass
    finally:
        await hub.disconnect(org_id, ws)
        log.info("WS disconnected org=%s total=%d", org_id, hub.total_connections())


@app.get("/health")
async def health():
    return {"status": "ok", "connections": hub.total_connections()}
