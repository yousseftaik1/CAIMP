from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from .config import settings
from .db import close_pool, get_conn, init_pool
from .redis_client import close_redis, init_redis
from .routers import agents, alert_rules, auth, orgs, servers, users

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    await init_redis()
    await _ensure_ca()
    yield
    await close_pool()
    await close_redis()


async def _ensure_ca() -> None:
    """Generate root CA on first boot if none exists."""
    from caimp_auth.pki import CAManager

    async with get_conn() as conn:
        if await conn.fetchrow("SELECT id FROM ca_config LIMIT 1"):
            return

    ca_mgr = CAManager(settings.ca_key_passphrase)
    cert_pem, encrypted_key = ca_mgr.generate_ca()
    expires_at = datetime.now(tz=timezone.utc) + timedelta(days=3650)

    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO ca_config (cert_pem, encrypted_key, expires_at) VALUES ($1, $2, $3)",
            cert_pem,
            encrypted_key,
            expires_at,
        )
    log.info("Root CA generated and stored in database")


app = FastAPI(title="CAIMP Admin API", version="2.0.0", lifespan=lifespan)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

app.include_router(auth.router)
app.include_router(orgs.router)
app.include_router(users.router)
app.include_router(servers.router)
app.include_router(agents.router)
app.include_router(alert_rules.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
