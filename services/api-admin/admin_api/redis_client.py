from __future__ import annotations

import redis.asyncio as aioredis

from .config import settings

_redis: aioredis.Redis | None = None


async def init_redis() -> None:
    global _redis
    _redis = aioredis.from_url(
        settings.redis_url,
        password=settings.redis_password or None,
        decode_responses=True,
    )


async def close_redis() -> None:
    if _redis:
        await _redis.close()


def get_redis() -> aioredis.Redis:
    assert _redis is not None
    return _redis
