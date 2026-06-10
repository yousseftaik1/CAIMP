#!/usr/bin/env python3
"""
CAIMP v2 Server Agent — main daemon entry point.

Usage:
    python main.py [--enroll TOKEN]

First-run (enrollment):
    python main.py --enroll <one_time_enrollment_token>

Subsequent starts:
    python main.py
    (or: systemctl start caimp-agent)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
import sys

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from caimp_agent.auth import EnrollmentManager, JWTManager
from caimp_agent.buffer import SQLiteBuffer
from caimp_agent.collectors import register_all
from caimp_agent.config import AgentConfig
from caimp_agent.exporter import BufferedOTLPExporter, buffer_replay_loop

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("caimp-agent")


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------
_shutdown_event = asyncio.Event()


def _handle_signal(*_):
    log.info("Shutdown signal received")
    _shutdown_event.set()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(cfg: AgentConfig) -> None:
    cfg.ensure_data_dir()

    enrollment = EnrollmentManager(cfg)
    jwt_mgr    = JWTManager(cfg)
    buffer     = SQLiteBuffer(cfg.buffer_path, cfg.buffer_max_mb, cfg.buffer_max_hours)

    # Check cert renewal
    if enrollment.is_enrolled() and enrollment.cert_needs_renewal():
        log.info("Agent cert approaching expiry — renewing …")
        try:
            enrollment.renew_cert()
        except Exception as exc:
            log.warning("Cert renewal failed: %s (continuing with existing cert)", exc)

    # Build OTLP exporter (mTLS when cert is available, plaintext otherwise)
    exporter = BufferedOTLPExporter.with_mtls(cfg, jwt_mgr, buffer)

    # OTLP resource: identifies this agent in all telemetry
    resource = Resource.create({
        "service.name":    "caimp-agent",
        "service.version": "2.0.0",
        "host.name":       cfg.server_name,
        "host.id":         socket.gethostname(),
        # org_id and server_id are stamped here so the Collector can read them
        "org.id":          os.getenv("CAIMP_ORG_ID", "unknown"),
        "server.id":       os.getenv("CAIMP_SERVER_ID", "unknown"),
    })

    reader = PeriodicExportingMetricReader(
        exporter,
        export_interval_millis=cfg.collection_interval_secs * 1000,
    )
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)

    meter = metrics.get_meter("caimp.agent", "2.0.0")
    register_all(meter)

    log.info(
        "Agent started — server=%s interval=%ds endpoint=%s",
        cfg.server_name,
        cfg.collection_interval_secs,
        cfg.otelcol_endpoint,
    )

    # Background tasks
    tasks = [
        asyncio.create_task(jwt_mgr.refresh_loop()),
        asyncio.create_task(buffer_replay_loop(exporter._otlp, buffer)),
    ]

    # Change reporters — track deployments, Docker events, packages, SSH, cron
    try:
        from caimp_agent.change_reporters import start_all_reporters
        server_id = os.getenv("CAIMP_SERVER_ID", "")
        jwt_token = jwt_mgr.current_token() if hasattr(jwt_mgr, "current_token") else ""
        if server_id and jwt_token:
            reporter_tasks = await start_all_reporters(cfg, server_id, jwt_token)
            tasks.extend(reporter_tasks)
    except Exception as exc:
        log.warning("Change reporters could not start: %s", exc)

    try:
        await _shutdown_event.wait()
    finally:
        log.info("Shutting down …")
        for t in tasks:
            t.cancel()
        provider.shutdown()
        buffer.close()
        log.info("Agent stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="CAIMP v2 Server Agent")
    parser.add_argument(
        "--enroll", metavar="TOKEN",
        help="Enroll this agent with the given one-time token, then exit",
    )
    args = parser.parse_args()

    cfg = AgentConfig()
    cfg.ensure_data_dir()

    if args.enroll:
        enrollment = EnrollmentManager(cfg)
        log.info("Starting enrollment …")
        enrollment.enroll(args.enroll)
        log.info("Enrollment complete. Run without --enroll to start the agent.")
        sys.exit(0)

    if not EnrollmentManager(cfg).is_enrolled():
        log.warning(
            "Agent not enrolled. Run:  python main.py --enroll <TOKEN>\n"
            "Continuing in unauthenticated mode (metrics will be sent without mTLS)."
        )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    try:
        loop.run_until_complete(run(cfg))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
