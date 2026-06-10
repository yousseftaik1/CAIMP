from __future__ import annotations

import json
import logging
import operator as op
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from .config import settings

log = logging.getLogger(__name__)

_OPS: dict[str, Any] = {
    ">":  op.gt,
    ">=": op.ge,
    "<":  op.lt,
    "<=": op.le,
    "==": op.eq,
}


class RuleEvaluator:
    def __init__(self, pool: asyncpg.Pool, redis: aioredis.Redis) -> None:
        self._pool = pool
        self._redis = redis

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def evaluate_batch(self, org_id: str, server_id: str) -> list[dict]:
        """
        Return a list of fired-rule dicts for a given org/server.
        Each entry has: rule, metric_name, value, threshold, server_id, org_id.
        """
        rules = await self._load_rules(org_id)
        if not rules:
            return []

        latest = await self._latest_metrics(org_id, server_id)
        if not latest:
            return []

        fired = []
        for rule in rules:
            cond = rule["condition_json"]
            metric_name = cond.get("metric_name")
            operator_str = cond.get("operator", ">")
            threshold = float(cond.get("threshold", 0))
            rule_server = cond.get("server_id")

            if rule_server and rule_server != server_id:
                continue

            value = latest.get(metric_name)
            if value is None:
                continue

            cmp_fn = _OPS.get(operator_str)
            if not cmp_fn or not cmp_fn(value, threshold):
                continue

            # Cooldown check — skip if recently fired
            cooldown_key = f"alert:cooldown:{rule['id']}:{server_id}"
            if await self._redis.exists(cooldown_key):
                continue

            cooldown_ttl = int(rule["cooldown_minutes"]) * 60
            await self._redis.setex(cooldown_key, cooldown_ttl, "1")

            fired.append({
                "rule": rule,
                "metric_name": metric_name,
                "value": value,
                "threshold": threshold,
                "server_id": server_id,
                "org_id": org_id,
            })

        return fired

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _load_rules(self, org_id: str) -> list[dict]:
        cache_key = f"alert_rules:{org_id}"
        raw = await self._redis.get(cache_key)
        if raw:
            return json.loads(raw)

        rows = await self._pool.fetch(
            "SELECT id, name, rule_type, condition_json, notification_channels, cooldown_minutes "
            "FROM alert_rules "
            "WHERE org_id = $1::uuid AND enabled = true",
            org_id,
        )
        rules = [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "rule_type": r["rule_type"],
                "condition_json": dict(r["condition_json"]),
                "notification_channels": list(r["notification_channels"]),
                "cooldown_minutes": r["cooldown_minutes"],
            }
            for r in rows
        ]
        await self._redis.setex(cache_key, settings.rules_cache_ttl, json.dumps(rules))
        return rules

    async def _latest_metrics(self, org_id: str, server_id: str) -> dict[str, float]:
        rows = await self._pool.fetch(
            "SELECT DISTINCT ON (metric_name) metric_name, value "
            "FROM metrics "
            "WHERE org_id = $1::uuid AND server_id = $2::uuid "
            "AND time > now() - INTERVAL '5 minutes' "
            "ORDER BY metric_name, time DESC",
            org_id, server_id,
        )
        return {r["metric_name"]: r["value"] for r in rows}
