from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(settings.postgres_dsn, min_size=2, max_size=10)


async def close_pool() -> None:
    if _pool:
        await _pool.close()


@asynccontextmanager
async def get_conn() -> AsyncGenerator[asyncpg.Connection, None]:
    assert _pool is not None
    async with _pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_tenant_conn(org_id: str) -> AsyncGenerator[asyncpg.Connection, None]:
    """Acquire a connection with RLS org context set for the current transaction."""
    from caimp_auth.rls import set_org_context

    assert _pool is not None
    async with _pool.acquire() as conn:
        async with conn.transaction():
            await set_org_context(conn, org_id)
            yield conn
