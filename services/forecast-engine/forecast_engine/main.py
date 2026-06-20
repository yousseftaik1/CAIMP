from __future__ import annotations

import asyncio
import logging
import os

from prometheus_client import start_http_server

from nats_client.client import NatsClient

from .config import settings
from .db import close_pool, get_pool, init_pool
from .ollama_client import is_ready as ollama_ready
from . import worker

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


async def _wait_ollama(retries: int = 30, delay: float = 10.0) -> None:
    for i in range(retries):
        if await ollama_ready():
            log.info("Ollama is ready")
            return
        log.info("Waiting for Ollama... attempt %d/%d", i + 1, retries)
        await asyncio.sleep(delay)
    log.warning(
        "Ollama not ready after %d attempts — forecasts will run without LLM narratives",
        retries,
    )


async def main() -> None:
    metrics_port = int(os.getenv("METRICS_PORT", "9094"))
    start_http_server(metrics_port)
    log.info("Prometheus metrics on :%d", metrics_port)

    await init_pool()
    log.info("Database pool ready")

    await _wait_ollama()

    async with NatsClient.connect(
        url=settings.nats_url,
        user=settings.nats_user,
        password=settings.nats_password,
    ) as nc:
        await worker.run(get_pool(), nc)

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
