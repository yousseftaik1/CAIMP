from __future__ import annotations

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    # Bypass RLS — alert engine writes across all orgs (anomaly_events, notifications)
    await conn.execute("SET ROLE caimp_service")


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        settings.postgres_dsn,
        min_size=2,
        max_size=8,
        init=_init_conn,
    )


async def close_pool() -> None:
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    return _pool
