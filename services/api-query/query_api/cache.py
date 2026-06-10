from __future__ import annotations

import hashlib
import json

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
        await _redis.aclose()


def _cache_key(prefix: str, **kwargs) -> str:
    payload = json.dumps(kwargs, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"qcache:{prefix}:{digest}"


async def get_cached(prefix: str, ttl_seconds: int = 30, **kwargs):
    """Return cached JSON value or None."""
    key = _cache_key(prefix, **kwargs)
    raw = await _redis.get(key)
    return json.loads(raw) if raw else None


async def set_cached(value, prefix: str, ttl_seconds: int = 30, **kwargs) -> None:
    key = _cache_key(prefix, **kwargs)
    await _redis.setex(key, ttl_seconds, json.dumps(value, default=str))
