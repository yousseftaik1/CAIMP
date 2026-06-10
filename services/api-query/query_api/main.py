from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from .cache import close_redis, init_redis
from .db import close_pool, init_pool
from .routers import ai, anomalies, dashboard, forecasts, incidents, metrics, reports, servers

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    await init_redis()
    yield
    await close_pool()
    await close_redis()


app = FastAPI(title="CAIMP Query API", version="2.0.0", lifespan=lifespan)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

app.include_router(metrics.router)
app.include_router(anomalies.router)
app.include_router(incidents.router)
app.include_router(servers.router)
app.include_router(ai.router)
app.include_router(forecasts.router)
app.include_router(reports.router)
app.include_router(dashboard.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
