"""
Typed NATS JetStream client for CAIMP v2.

Usage:
    async with NatsClient.connect(url, user, password) as nc:
        await nc.publish(Subjects.anomaly_detected(org_id, "critical"), event)
        async for msg in nc.subscribe("ANOMALIES", "ai-worker"):
            event = AnomalyEvent.model_validate_json(msg.data)
            await msg.ack()
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Type, TypeVar

import nats
from nats.aio.client import Client
from nats.js import JetStreamContext
from nats.js.api import ConsumerConfig, DeliverPolicy
from pydantic import BaseModel

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)


class NatsClient:
    def __init__(self, nc: Client, js: JetStreamContext) -> None:
        self._nc = nc
        self._js = js

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    @asynccontextmanager
    async def connect(
        cls,
        url: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> AsyncIterator["NatsClient"]:
        url      = url      or os.environ.get("NATS_URL",      "nats://localhost:4222")
        user     = user     or os.environ.get("NATS_USER",     "")
        password = password or os.environ.get("NATS_PASSWORD", "")

        kwargs: dict = {"connect_timeout": 10, "max_reconnect_attempts": -1}
        if user and password:
            kwargs["user"]     = user
            kwargs["password"] = password

        nc = await nats.connect(url, **kwargs)
        js = nc.jetstream()
        log.info("Connected to NATS at %s", url)

        try:
            yield cls(nc, js)
        finally:
            await nc.drain()
            log.info("NATS connection drained")

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, subject: str, payload: BaseModel | dict | bytes) -> None:
        if isinstance(payload, BaseModel):
            data = payload.model_dump_json().encode()
        elif isinstance(payload, dict):
            data = json.dumps(payload).encode()
        else:
            data = payload
        ack = await self._js.publish(subject, data)
        log.debug("Published to %s (seq=%d)", subject, ack.seq)

    # ------------------------------------------------------------------
    # Pull consumer (durable)
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        stream: str,
        consumer_name: str,
        subject_filter: str | None = None,
        batch_size: int = 10,
    ) -> AsyncIterator:
        cfg = ConsumerConfig(
            durable_name=consumer_name,
            deliver_policy=DeliverPolicy.ALL,
            ack_wait=30,
            max_deliver=5,
            filter_subject=subject_filter,
        )
        psub = await self._js.pull_subscribe(
            subject=subject_filter or ">",
            stream=stream,
            durable=consumer_name,
            config=cfg,
        )
        return psub

    # ------------------------------------------------------------------
    # Typed fetch helper
    # ------------------------------------------------------------------

    async def fetch_one(
        self,
        stream: str,
        consumer_name: str,
        model: Type[M],
        subject_filter: str | None = None,
    ) -> tuple[M, object] | None:
        sub = await self.subscribe(stream, consumer_name, subject_filter)
        try:
            msgs = await sub.fetch(1, timeout=5)
            if not msgs:
                return None
            msg = msgs[0]
            return model.model_validate_json(msg.data), msg
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Subscribe push (for WS Gateway fan-out)
    # ------------------------------------------------------------------

    async def push_subscribe(
        self,
        subject: str,
        cb: Callable,
    ) -> object:
        return await self._nc.subscribe(subject, cb=cb)

    # ------------------------------------------------------------------
    # Core client access (for advanced use)
    # ------------------------------------------------------------------

    @property
    def js(self) -> JetStreamContext:
        return self._js

    @property
    def nc(self) -> Client:
        return self._nc


# ---------------------------------------------------------------------------
# Module-level singleton helper (for FastAPI lifespan)
# ---------------------------------------------------------------------------

_client: NatsClient | None = None


def get_client() -> NatsClient:
    if _client is None:
        raise RuntimeError("NatsClient not initialised. Call set_client() first.")
    return _client


def set_client(client: NatsClient) -> None:
    global _client
    _client = client
