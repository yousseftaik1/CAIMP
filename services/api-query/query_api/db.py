from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg

from .config import settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        settings.postgres_dsn,
        min_size=2,
        max_size=10,
        max_inactive_connection_lifetime=60,
    )


async def close_pool() -> None:
    if _pool:
        await _pool.close()


async def _get_pool() -> asyncpg.Pool:
    """Return pool, reinitialising if postgres restarted."""
    global _pool
    if _pool is None:
        await init_pool()
        return _pool
    try:
        async with asyncio.timeout(3):
            async with _pool.acquire() as conn:
                await conn.execute("SELECT 1")
        return _pool
    except Exception:
        log.warning("Pool unhealthy — reinitialising")
        try:
            await _pool.close()
        except Exception:
            pass
        await init_pool()
        return _pool


@asynccontextmanager
async def get_tenant_conn(org_id: str) -> AsyncGenerator[asyncpg.Connection, None]:
    """Read-only tenant connection with RLS context set."""
    from caimp_auth.rls import set_org_context

    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await set_org_context(conn, org_id)
            yield conn
