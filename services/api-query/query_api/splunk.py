"""
Lightweight Splunk REST client for metric queries in the Query API.

Only implements what the metrics router needs: oneshot mstats export.
For the full Splunk client (two-phase search, KV Store baselines) see
services/ai-orchestrator/splunk_client.py.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx

log = logging.getLogger(__name__)

# ── index / span auto-selection ───────────────────────────────────────────────


def select_index_and_span(hours: float) -> tuple[str, str]:
    """
    Choose the right summary index and bucket span for a given time range.
    Mirrors the identical function in services/ai-orchestrator/context_builder.py.
    """
    if hours <= 1:
        return "caimp_metrics", "1m"
    elif hours <= 12:
        return "caimp_metrics", "5m"
    elif hours <= 72:
        return "caimp_metrics_5m", "5m"
    elif hours <= 720:
        return "caimp_metrics_1h", "1h"
    else:
        return "caimp_metrics_1d", "1d"


def _val_field(index: str) -> str:
    """avg(_value) for raw index, avg(avg_val) for summary indexes."""
    return "_value" if index == "caimp_metrics" else "avg_val"


# ── client ────────────────────────────────────────────────────────────────────


class SplunkMetricsClient:
    """Thin httpx wrapper for Splunk metric queries."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_tls: bool = False,
    ) -> None:
        self._base = f"https://{host}:8089"
        self._auth = (username, password)
        self._http = httpx.AsyncClient(
            verify=verify_tls,
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        )

    async def query_metrics(
        self,
        metric_name: str,
        host: str,
        org_id: str,
        index: str,
        span: str,
        earliest: str,
        latest: str,
    ) -> list[dict]:
        """
        Run an mstats oneshot export and return [{time, value}] rows.
        Returns empty list on any Splunk error.
        """
        vf = _val_field(index)
        spl = (
            f"| mstats avg({vf}) as val "
            f"WHERE index={index} "
            f'metric_name="{metric_name}" host="{host}" '
            f"span={span} "
            f'| eval ts=strftime(_time, "%Y-%m-%dT%H:%M:%SZ") '
            f"| table ts, val"
        )
        try:
            resp = await self._http.post(
                f"{self._base}/services/search/jobs/export",
                auth=self._auth,
                data={
                    "search": spl,
                    "earliest_time": earliest,
                    "latest_time": latest,
                    "output_mode": "json",
                    "count": "0",
                },
            )
            resp.raise_for_status()
        except Exception as exc:
            log.warning(f"Splunk mstats query failed: {exc}")
            return []

        rows: list[dict] = []
        for raw_line in resp.text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if obj.get("preview"):
                continue
            result = obj.get("result", {})
            ts_raw = result.get("ts") or result.get("_time")
            val = result.get("val")
            if ts_raw is None or val is None:
                continue
            try:
                t = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            try:
                rows.append({"time": t, "value": float(val)})
            except (ValueError, TypeError):
                continue

        return rows

    async def close(self) -> None:
        await self._http.aclose()
