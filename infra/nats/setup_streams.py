#!/usr/bin/env python3
"""
CAIMP v2 — NATS JetStream stream bootstrap.
Creates (or verifies) the five canonical streams on startup.
Runs as a one-shot service in Docker Compose.
"""

import asyncio
import logging
import os
import sys

import nats
from nats.js.api import (
    DiscardPolicy,
    RetentionPolicy,
    StorageType,
    StreamConfig,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

NATS_URL      = os.environ.get("NATS_URL",      "nats://localhost:4222")
NATS_USER     = os.environ.get("NATS_USER",     "caimp")
NATS_PASSWORD = os.environ.get("NATS_PASSWORD", "")

# Stream definitions
STREAMS: list[StreamConfig] = [
    StreamConfig(
        name="METRICS",
        subjects=["metric.received.>"],
        retention=RetentionPolicy.LIMITS,
        storage=StorageType.FILE,
        max_age=86_400,           # 24 h in seconds
        max_bytes=10 * 1024 ** 3, # 10 GB
        discard=DiscardPolicy.OLD,
        num_replicas=1,
        description="Raw metric batches from agents via Telemetry Writer",
    ),
    StreamConfig(
        name="ANOMALIES",
        subjects=["anomaly.detected.>"],
        retention=RetentionPolicy.LIMITS,
        storage=StorageType.FILE,
        max_age=7 * 86_400,       # 7 days
        discard=DiscardPolicy.OLD,
        num_replicas=1,
        description="Anomaly events from Telemetry Writer, consumed by AI Worker + Alert Engine",
    ),
    StreamConfig(
        name="AI_OUT",
        subjects=["ai.explanation.ready.>", "ai.explanation.failed.>"],
        retention=RetentionPolicy.LIMITS,
        storage=StorageType.FILE,
        max_age=30 * 86_400,      # 30 days
        discard=DiscardPolicy.OLD,
        num_replicas=1,
        description="AI explanation results, consumed by WS Gateway + Query API",
    ),
    StreamConfig(
        name="CHAT",
        subjects=["chat.requested.>"],
        retention=RetentionPolicy.LIMITS,
        storage=StorageType.FILE,
        max_age=3_600,            # 1 h
        discard=DiscardPolicy.OLD,
        num_replicas=1,
        description="Chat session messages, consumed by AI Worker",
    ),
    StreamConfig(
        name="AUDIT",
        subjects=["audit.log.>"],
        retention=RetentionPolicy.LIMITS,
        storage=StorageType.FILE,
        max_age=90 * 86_400,      # 90 days
        discard=DiscardPolicy.OLD,
        num_replicas=1,
        description="Audit events from Admin API write paths",
    ),
    StreamConfig(
        name="FORECASTS",
        subjects=["forecast.>"],
        retention=RetentionPolicy.LIMITS,
        storage=StorageType.FILE,
        max_age=30 * 86_400,      # 30 days
        discard=DiscardPolicy.OLD,
        num_replicas=1,
        description="Predictive forecast events from Forecast Engine",
    ),
    StreamConfig(
        name="CHANGES",
        subjects=["change.detected.>"],
        retention=RetentionPolicy.LIMITS,
        storage=StorageType.FILE,
        max_age=7 * 86_400,       # 7 days
        discard=DiscardPolicy.OLD,
        num_replicas=1,
        description="Change events from change-tracker: deployments, restarts, config, packages, SSH",
    ),
    StreamConfig(
        name="ROOT_CAUSE",
        subjects=["rootcause.ready.>"],
        retention=RetentionPolicy.LIMITS,
        storage=StorageType.FILE,
        max_age=30 * 86_400,      # 30 days
        discard=DiscardPolicy.OLD,
        num_replicas=1,
        description="Root-cause analysis results from correlation-engine → WS Gateway → browser",
    ),
]


async def bootstrap() -> None:
    credentials = {}
    if NATS_USER and NATS_PASSWORD:
        credentials = {"user": NATS_USER, "password": NATS_PASSWORD}

    log.info("Connecting to NATS at %s", NATS_URL)
    nc = await nats.connect(NATS_URL, **credentials, connect_timeout=10)
    js = nc.jetstream()

    for cfg in STREAMS:
        try:
            info = await js.find_stream(cfg.name)
            log.info("Stream %-10s already exists (msgs=%d)", cfg.name, info.state.messages)
        except Exception:
            await js.add_stream(config=cfg)
            log.info("Stream %-10s created", cfg.name)

    await nc.drain()
    log.info("NATS stream bootstrap complete")


if __name__ == "__main__":
    try:
        asyncio.run(bootstrap())
    except Exception as exc:
        log.error("Bootstrap failed: %s", exc)
        sys.exit(1)
