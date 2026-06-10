from __future__ import annotations

import asyncpg


async def set_org_context(conn: asyncpg.Connection, org_id: str) -> None:
    """Set caimp.current_org_id for the current transaction (RLS enforcement)."""
    await conn.execute(
        "SELECT set_config('caimp.current_org_id', $1, true)",
        str(org_id),
    )


async def set_service_role(conn: asyncpg.Connection) -> None:
    """Switch to caimp_service role to bypass RLS for cross-org writes."""
    await conn.execute("SET LOCAL ROLE caimp_service")
