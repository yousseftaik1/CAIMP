from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Optional: OTLP protobuf support
try:
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
        ExportMetricsServiceRequest as MetricsRequest,
    )
    from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
        ExportLogsServiceRequest as LogsRequest,
    )

    PROTO_AVAILABLE = True
except ImportError:
    PROTO_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","service":"splunk-hec-bridge","event":"%(message)s"}',
)
log = logging.getLogger(__name__)

SPLUNK_HEC_URL = os.environ["SPLUNK_HEC_URL"]
HEC_TOKEN_METRICS = os.environ["SPLUNK_HEC_TOKEN_METRICS"]
HEC_TOKEN_LOGS = os.environ.get("SPLUNK_HEC_TOKEN_LOGS", "")
SPLUNK_VERIFY_TLS = os.environ.get("SPLUNK_VERIFY_TLS", "false").lower() == "true"
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
HEC_BATCH_SIZE = 100

redis_client: aioredis.Redis | None = None
http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, http_client
    redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)
    http_client = httpx.AsyncClient(verify=SPLUNK_VERIFY_TLS, timeout=10.0)
    log.info("startup complete")
    yield
    await redis_client.aclose()
    await http_client.aclose()


app = FastAPI(title="Splunk HEC Bridge", version="1.0.0", lifespan=lifespan)


# ── internal helpers ──────────────────────────────────────────────────────────


def _attr_map(attributes) -> dict[str, str]:
    """OTLP repeated KeyValue → plain dict."""
    result: dict[str, str] = {}
    for kv in attributes:
        v = kv.value
        if v.HasField("string_value"):
            result[kv.key] = v.string_value
        elif v.HasField("double_value"):
            result[kv.key] = str(v.double_value)
        elif v.HasField("int_value"):
            result[kv.key] = str(v.int_value)
        elif v.HasField("bool_value"):
            result[kv.key] = str(v.bool_value).lower()
    return result


def _dp_value(dp) -> float:
    """Extract numeric value from a NumberDataPoint."""
    if dp.HasField("as_double"):
        return dp.as_double
    return float(dp.as_int)


async def _post_hec(events: list[dict], token: str) -> None:
    """Batch POST events to Splunk HEC (newline-delimited JSON)."""
    for i in range(0, len(events), HEC_BATCH_SIZE):
        batch = events[i : i + HEC_BATCH_SIZE]
        body = "\n".join(json.dumps(e) for e in batch)
        resp = await http_client.post(
            SPLUNK_HEC_URL,
            headers={
                "Authorization": f"Splunk {token}",
                "Content-Type": "application/json",
            },
            content=body.encode(),
        )
        if resp.status_code == 403:
            log.error("HEC auth failure (403) — check token")
            raise ValueError("HEC auth failure")
        if resp.status_code not in (200, 204):
            log.error(f"HEC error {resp.status_code}: {resp.text[:300]}")
            raise ValueError(f"HEC non-200: {resp.status_code}")


async def _write_redis(
    org_id: str, server_id: str, metric_name: str, value: float
) -> None:
    """Write latest metric value to Redis for live dashboard (TTL 90s)."""
    try:
        await redis_client.setex(
            f"live:{org_id}:{server_id}:{metric_name}", 90, str(value)
        )
    except Exception as exc:
        log.warning(f"Redis live-write failed (non-fatal): {exc}")


# ── OTLP protobuf metric parsing ──────────────────────────────────────────────


def _parse_otlp_proto_metrics(raw: bytes) -> list[dict]:
    """
    Parse OTLP ExportMetricsServiceRequest protobuf.
    Returns list of (resource_attrs, metric_name, value, ts_ns) tuples
    grouped per resource as HEC events.
    """
    req = MetricsRequest()
    req.ParseFromString(raw)

    hec_events: list[dict] = []

    for rm in req.resource_metrics:
        res_attrs = _attr_map(rm.resource.attributes)
        host = res_attrs.get("host.name", "unknown")
        org_id = res_attrs.get("caimp.org_id", "")
        server_id = res_attrs.get("caimp.server_id", "")
        agent_ver = res_attrs.get("service.version", "unknown")

        # Collect all metrics for this resource into one HEC event
        fields: dict[str, Any] = {
            "org_id": org_id,
            "server_id": server_id,
            "agent_version": agent_ver,
        }
        ts_epoch: float = time.time()

        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                name = metric.name
                dps = []
                if metric.HasField("gauge"):
                    dps = list(metric.gauge.data_points)
                elif metric.HasField("sum"):
                    dps = list(metric.sum.data_points)

                for dp in dps:
                    val = _dp_value(dp)
                    if dp.time_unix_nano:
                        ts_epoch = dp.time_unix_nano / 1e9
                    fields[f"metric_name:{name}"] = val
                    # async Redis write scheduled after we return
                    fields[f"__live__{name}"] = (org_id, server_id, name, val)

        # Strip the __live__ sentinel before building HEC event
        live_writes = {k: v for k, v in fields.items() if k.startswith("__live__")}
        clean_fields = {k: v for k, v in fields.items() if not k.startswith("__live__")}

        hec_events.append(
            {
                "_live": live_writes,
                "event": {
                    "time": ts_epoch,
                    "event": "metric",
                    "host": host,
                    "source": f"caimp-agent:{agent_ver}",
                    "sourcetype": "caimp:metrics",
                    "index": "caimp_metrics",
                    "fields": clean_fields,
                },
            }
        )

    return hec_events


def _parse_json_metrics(body: dict) -> list[dict]:
    """
    Parse simple JSON test format:
    {
      "resource_attributes": {"host.name": "...", "caimp.org_id": "...", ...},
      "metrics": [{"name": "...", "value": 87.3, "timestamp_unix_nano": ...}]
    }
    """
    ra = body.get("resource_attributes", {})
    host = ra.get("host.name", "unknown")
    org_id = ra.get("caimp.org_id", "")
    server_id = ra.get("caimp.server_id", "")
    agent_ver = ra.get("service.version", "unknown")

    fields: dict[str, Any] = {
        "org_id": org_id,
        "server_id": server_id,
        "agent_version": agent_ver,
    }
    live_writes: dict[str, tuple] = {}
    ts_epoch = time.time()

    for m in body.get("metrics", []):
        name = m["name"]
        val = float(m["value"])
        if m.get("timestamp_unix_nano"):
            ts_epoch = m["timestamp_unix_nano"] / 1e9
        fields[f"metric_name:{name}"] = val
        live_writes[name] = (org_id, server_id, name, val)

    return [
        {
            "_live": live_writes,
            "event": {
                "time": ts_epoch,
                "event": "metric",
                "host": host,
                "source": f"caimp-agent:{agent_ver}",
                "sourcetype": "caimp:metrics",
                "index": "caimp_metrics",
                "fields": fields,
            },
        }
    ]


# ── routes ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "service": "splunk-hec-bridge"}


@app.post("/v1/metrics")
async def ingest_metrics(request: Request):
    content_type = request.headers.get("content-type", "")
    raw = await request.body()

    try:
        if "application/x-protobuf" in content_type and PROTO_AVAILABLE:
            parsed = _parse_otlp_proto_metrics(raw)
        else:
            # JSON fallback (test payloads or if proto lib not available)
            parsed = _parse_json_metrics(json.loads(raw))
    except Exception as exc:
        log.error(f"Parse error: {exc}")
        return JSONResponse(
            {"error": "parse_failed", "detail": str(exc)}, status_code=400
        )

    hec_events = [p["event"] for p in parsed]
    live_data = {k: v for p in parsed for k, v in p["_live"].items()}

    try:
        await _post_hec(hec_events, HEC_TOKEN_METRICS)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    # Write to Redis after successful HEC post
    for entry in live_data.values():
        org_id, server_id, metric_name, value = entry
        await _write_redis(org_id, server_id, metric_name, value)

    log.info(f"ingested {len(hec_events)} metric event(s)")
    return {"message": "ok", "events_sent": len(hec_events)}


@app.post("/v1/logs")
async def ingest_logs(request: Request):
    content_type = request.headers.get("content-type", "")
    raw = await request.body()

    hec_events: list[dict] = []

    try:
        if "application/x-protobuf" in content_type and PROTO_AVAILABLE:
            req = LogsRequest()
            req.ParseFromString(raw)
            for rl in req.resource_logs:
                res_attrs = _attr_map(rl.resource.attributes)
                host = res_attrs.get("host.name", "unknown")
                org_id = res_attrs.get("caimp.org_id", "")
                server_id = res_attrs.get("caimp.server_id", "")
                for sl in rl.scope_logs:
                    for lr in sl.log_records:
                        ts = (
                            lr.time_unix_nano / 1e9
                            if lr.time_unix_nano
                            else time.time()
                        )
                        hec_events.append(
                            {
                                "time": ts,
                                "event": lr.body.string_value,
                                "host": host,
                                "source": res_attrs.get("service.name", "caimp-agent"),
                                "sourcetype": "caimp:logs",
                                "index": "caimp_logs",
                                "fields": {"org_id": org_id, "server_id": server_id},
                            }
                        )
        else:
            body = json.loads(raw)
            ra = body.get("resource_attributes", {})
            host = ra.get("host.name", "unknown")
            org_id = ra.get("caimp.org_id", "")
            server_id = ra.get("caimp.server_id", "")
            for entry in body.get("logs", []):
                hec_events.append(
                    {
                        "time": entry.get("timestamp", time.time()),
                        "event": entry.get("message", ""),
                        "host": host,
                        "source": entry.get("source", "/var/log/syslog"),
                        "sourcetype": "caimp:logs",
                        "index": "caimp_logs",
                        "fields": {"org_id": org_id, "server_id": server_id},
                    }
                )
    except Exception as exc:
        log.error(f"Log parse error: {exc}")
        return JSONResponse(
            {"error": "parse_failed", "detail": str(exc)}, status_code=400
        )

    if not hec_events:
        return {"message": "ok", "events_sent": 0}

    if not HEC_TOKEN_LOGS:
        log.warning("HEC_TOKEN_LOGS not set — dropping log events")
        return {"message": "ok", "events_sent": 0}

    try:
        await _post_hec(hec_events, HEC_TOKEN_LOGS)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    log.info(f"ingested {len(hec_events)} log event(s)")
    return {"message": "ok", "events_sent": len(hec_events)}
