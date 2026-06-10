from __future__ import annotations

import asyncio
import logging
import os

from prometheus_client import start_http_server

from nats_client.client import NatsClient

from .config import settings
from .db import close_pool, init_pool
from . import worker

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


async def main() -> None:
    metrics_port = int(os.getenv("METRICS_PORT", "9093"))
    start_http_server(metrics_port)
    log.info("Prometheus metrics on :%d", metrics_port)

    await init_pool()
    log.info("Database pool ready")

    async with NatsClient.connect(
        url=settings.nats_url,
        user=settings.nats_user,
        password=settings.nats_password,
    ) as nc:
        await worker.run(nc)

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
