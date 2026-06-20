#!/usr/bin/env python3
"""
CAIMP Demo Agent — sends real CPU/RAM/disk metrics from THIS machine
to the local telemetry-writer every 20 seconds.

Usage (from project root, with docker-compose running):
    pip install psutil requests
    python services/agent/demo_agent.py

The agent uses the seed demo-server-01 identity so metrics appear
immediately on the dashboard at http://localhost:3000.

To send for a different server pass env vars:
    CAIMP_ORG_ID=<uuid>    CAIMP_SERVER_ID=<uuid>
    CAIMP_SERVER_NAME=web-server-01
    python services/agent/demo_agent.py
"""

from __future__ import annotations

import logging
import os
import time

import psutil
import requests

# ── Config ──────────────────────────────────────────────────────────────────
TELEMETRY_URL = os.getenv("CAIMP_TW_URL", "http://localhost:4319")
ORG_ID = os.getenv("CAIMP_ORG_ID", "00000000-0000-0000-0000-000000000001")
SERVER_ID = os.getenv("CAIMP_SERVER_ID", "00000000-0000-0000-0000-000000000011")
SERVER_NAME = os.getenv("CAIMP_SERVER_NAME", "demo-server-01")
INTERVAL = int(os.getenv("CAIMP_INTERVAL", "20"))

# Optional overrides for demo — set to 0-100 to override real readings
CPU_OVERRIDE = float(os.getenv("CAIMP_CPU", "0"))  # 0 = use real value
RAM_OVERRIDE = float(os.getenv("CAIMP_RAM", "0"))
DISK_OVERRIDE = float(os.getenv("CAIMP_DISK", "0"))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("demo-agent")


def collect() -> list[dict]:
    """Collect CPU, RAM, and disk metrics as OTLP raw records."""
    now_ns = int(time.time() * 1e9)
    resource = {"org.id": ORG_ID, "server.id": SERVER_ID}

    records = []

    # ── CPU utilization (per-core average, 0-1 fraction) ──────────────────
    real_cpu = psutil.cpu_percent(interval=1)  # blocks 1 s
    cpu_pct = CPU_OVERRIDE if CPU_OVERRIDE > 0 else real_cpu
    records.append(
        {
            "name": "system.cpu.utilization",
            "resource_attributes": resource,
            "data_points": [{"value": cpu_pct / 100.0, "time_unix_nano": now_ns}],
        }
    )

    # ── Memory utilization (0-1 fraction) ────────────────────────────────
    mem = psutil.virtual_memory()
    ram_pct = RAM_OVERRIDE if RAM_OVERRIDE > 0 else mem.percent
    records.append(
        {
            "name": "system.memory.utilization",
            "resource_attributes": resource,
            "data_points": [{"value": ram_pct / 100.0, "time_unix_nano": now_ns}],
        }
    )

    # ── Disk utilization — root / (0-1 fraction) ─────────────────────────
    try:
        root_path = "C:\\" if os.name == "nt" else "/"
        disk = psutil.disk_usage(root_path)
        disk_pct = DISK_OVERRIDE if DISK_OVERRIDE > 0 else disk.percent
        records.append(
            {
                "name": "system.filesystem.utilization",
                "resource_attributes": resource,
                "data_points": [
                    {
                        "value": disk_pct / 100.0,
                        "time_unix_nano": now_ns,
                        "attributes": {"mountpoint": root_path},
                    }
                ],
            }
        )
    except Exception:
        pass

    return records


def send(records: list[dict]) -> None:
    url = f"{TELEMETRY_URL}/v1/metrics/raw"
    try:
        resp = requests.post(url, json=records, timeout=10)
        if resp.ok:
            cpu_val = next(
                (
                    r["data_points"][0]["value"]
                    for r in records
                    if r["name"] == "system.cpu.utilization"
                ),
                0,
            )
            mem_val = next(
                (
                    r["data_points"][0]["value"]
                    for r in records
                    if r["name"] == "system.memory.utilization"
                ),
                0,
            )
            suffix = " [OVERRIDE]" if CPU_OVERRIDE > 0 or RAM_OVERRIDE > 0 else ""
            log.info(
                "Sent %d metrics  CPU=%.1f%%  RAM=%.1f%%%s",
                len(records),
                cpu_val * 100,
                mem_val * 100,
                suffix,
            )
        else:
            log.warning(
                "Telemetry writer returned %s: %s", resp.status_code, resp.text[:200]
            )
    except requests.exceptions.ConnectionError:
        log.error(
            "Cannot reach telemetry-writer at %s — is docker-compose running?", url
        )
    except Exception as exc:
        log.error("Send failed: %s", exc)


def main() -> None:
    log.info(
        "Demo agent starting — server=%s  interval=%ds  endpoint=%s",
        SERVER_NAME,
        INTERVAL,
        TELEMETRY_URL,
    )
    log.info("Metrics will appear on demo-server-01 at http://localhost:3000")

    while True:
        try:
            records = collect()
            send(records)
        except KeyboardInterrupt:
            log.info("Stopped")
            break
        except Exception as exc:
            log.error("Collect error: %s", exc)
        time.sleep(INTERVAL - 1)  # -1 because cpu_percent blocks 1 s


if __name__ == "__main__":
    main()
