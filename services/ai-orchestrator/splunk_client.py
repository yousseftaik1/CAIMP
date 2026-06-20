"""
Splunk REST API client for the AI Orchestrator.

Two query methods:
  run_search()         — two-phase: create job → poll until done → fetch results.
                         Use for complex multi-step SPL that needs full job lifecycle.
  run_search_oneshot() — single export request, no polling.
                         Faster for simple queries; use for context builder SPL.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import httpx

log = logging.getLogger(__name__)


class SplunkQueryError(Exception):
    pass


class SplunkClient:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_tls: bool = False,
    ) -> None:
        self.base = host.rstrip("/")
        self.auth = (username, password)
        self.client = httpx.AsyncClient(
            verify=verify_tls,
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        )

    # ── two-phase search ──────────────────────────────────────────────────────

    async def run_search(
        self,
        spl: str,
        earliest: str = "-1h",
        latest: str = "now",
        count: int = 100,
        poll_interval: float = 1.0,
        max_wait: int = 30,
    ) -> list[dict]:
        """
        POST a search job, poll until done, fetch results.
        Raises SplunkQueryError on HTTP failure or timeout.
        """
        # Phase 1 — create job
        create_resp = await self.client.post(
            f"{self.base}/services/search/jobs",
            auth=self.auth,
            data={
                "search": spl,
                "earliest_time": earliest,
                "latest_time": latest,
                "output_mode": "json",
            },
        )
        if create_resp.status_code != 201:
            raise SplunkQueryError(
                f"Job create failed {create_resp.status_code}: {create_resp.text[:200]}"
            )
        sid = create_resp.json()["sid"]

        # Phase 2 — poll until done
        for _ in range(max_wait):
            status_resp = await self.client.get(
                f"{self.base}/services/search/jobs/{sid}",
                auth=self.auth,
                params={"output_mode": "json"},
            )
            if status_resp.status_code != 200:
                raise SplunkQueryError(
                    f"Job status check failed {status_resp.status_code}"
                )
            entry = status_resp.json()["entry"][0]["content"]
            if entry.get("isDone"):
                break
            await asyncio.sleep(poll_interval)
        else:
            raise SplunkQueryError(f"Search timed out after {max_wait}s (sid={sid})")

        # Phase 3 — fetch results
        results_resp = await self.client.get(
            f"{self.base}/services/search/jobs/{sid}/results",
            auth=self.auth,
            params={"output_mode": "json", "count": count},
        )
        if results_resp.status_code != 200:
            raise SplunkQueryError(f"Result fetch failed {results_resp.status_code}")
        return results_resp.json().get("results", [])

    # ── oneshot export ────────────────────────────────────────────────────────

    async def run_search_oneshot(
        self,
        spl: str,
        earliest: str = "-1h",
        latest: str = "now",
        count: int = 100,
    ) -> list[dict]:
        """
        Single POST to the export endpoint — no job polling, faster for
        simple queries. Returns results parsed from newline-delimited JSON.
        """
        resp = await self.client.post(
            f"{self.base}/services/search/jobs/export",
            auth=self.auth,
            data={
                "search": spl,
                "earliest_time": earliest,
                "latest_time": latest,
                "output_mode": "json",
                "count": count,
            },
        )
        if resp.status_code not in (200, 204):
            raise SplunkQueryError(
                f"Oneshot export failed {resp.status_code}: {resp.text[:200]}"
            )

        results: list[dict] = []
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("result"):
                    results.append(obj["result"])
            except json.JSONDecodeError:
                pass
        return results

    # ── KV Store lookup ───────────────────────────────────────────────────────

    async def get_baseline(self, host: str, metric_name: str) -> dict:
        """
        Read 24h rolling baseline stats from the caimp_baselines KV Store lookup.
        Returns empty dict if no baseline exists yet for this host+metric.
        """
        results = await self.run_search_oneshot(
            f"| inputlookup caimp_baselines "
            f'WHERE host="{host}" metric_name="{metric_name}" '
            f"| head 1",
            earliest="-1m",
            latest="now",
        )
        return results[0] if results else {}

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def close(self) -> None:
        await self.client.aclose()


# ── quick smoke test ──────────────────────────────────────────────────────────
# Run with:
#   SPLUNK_HOST=https://host:8089 SPLUNK_USERNAME=admin SPLUNK_PASSWORD=pw \
#   python services/ai-orchestrator/splunk_client.py

if __name__ == "__main__":
    import asyncio

    async def _test() -> None:
        client = SplunkClient(
            host=os.environ["SPLUNK_HOST"],
            username=os.environ["SPLUNK_USERNAME"],
            password=os.environ["SPLUNK_PASSWORD"],
        )
        print("Testing run_search_oneshot against index=_internal ...")
        rows = await client.run_search_oneshot(
            "search index=_internal | head 3",
            earliest="-5m",
        )
        print(f"  Got {len(rows)} rows")
        if rows:
            print(f"  First row keys: {list(rows[0].keys())}")

        print("Testing run_search (two-phase) against index=_internal ...")
        rows2 = await client.run_search(
            "search index=_internal | head 3",
            earliest="-5m",
        )
        print(f"  Got {len(rows2)} rows")

        print("Testing get_baseline ...")
        baseline = await client.get_baseline("web-01", "system.cpu.utilization")
        print(f"  Baseline: {baseline or '(no data yet)'}")

        await client.close()
        print("All tests passed.")

    asyncio.run(_test())
