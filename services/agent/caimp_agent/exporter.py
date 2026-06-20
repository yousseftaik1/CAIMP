"""
OTLP/gRPC exporter with mTLS + JWT auth + SQLite fallback buffer.

When the Collector is reachable the exporter forwards directly.
On failure the batch is serialised and written to the SQLite buffer;
a background task drains the buffer whenever the endpoint comes back.
"""

from __future__ import annotations

import asyncio
import logging
import time

import grpc
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    MetricExportResult,
    MetricsData,
)
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

from .auth import JWTManager
from .buffer import SQLiteBuffer
from .config import AgentConfig

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _metrics_data_to_records(data: MetricsData) -> list[dict]:
    """Convert MetricsData to a list of dicts for buffer storage."""
    records = []
    for rm in data.resource_metrics:
        resource_attrs = dict(rm.resource.attributes)
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                data_points = []
                # Handle gauge / sum / histogram
                src = getattr(metric, "data", None)
                if src is not None:
                    raw_points = getattr(src, "data_points", [])
                    for dp in raw_points:
                        point = {
                            "time_unix_nano": getattr(dp, "time_unix_nano", 0),
                            "value": getattr(dp, "value", getattr(dp, "sum", 0)),
                            "attributes": dict(getattr(dp, "attributes", {})),
                        }
                        data_points.append(point)

                records.append(
                    {
                        "resource_attributes": resource_attrs,
                        "scope": sm.scope.name if sm.scope else "",
                        "name": metric.name,
                        "unit": metric.unit,
                        "description": metric.description,
                        "data_points": data_points,
                        "captured_at": time.time(),
                    }
                )
    return records


# ---------------------------------------------------------------------------
# Buffered exporter
# ---------------------------------------------------------------------------


class BufferedOTLPExporter(MetricExporter):
    """
    Wraps OTLPMetricExporter and falls back to SQLiteBuffer on failure.
    Prefer to use with_mtls() to construct an instance.
    """

    def __init__(
        self,
        otlp_exporter: OTLPMetricExporter,
        buffer: SQLiteBuffer,
    ) -> None:
        self._otlp = otlp_exporter
        self._buffer = buffer
        self._online = True

    @classmethod
    def with_mtls(
        cls,
        cfg: AgentConfig,
        jwt_manager: JWTManager,
        buffer: SQLiteBuffer,
    ) -> "BufferedOTLPExporter":
        """Build the exporter with mTLS channel credentials + JWT call credentials."""
        if cfg.use_tls and cfg.cert_path.exists() and cfg.ca_path.exists():
            ca_cert = cfg.ca_path.read_bytes()
            client_cert = cfg.cert_path.read_bytes()
            client_key = cfg.key_path.read_bytes()

            ssl_creds = grpc.ssl_channel_credentials(
                root_certificates=ca_cert,
                private_key=client_key,
                certificate_chain=client_cert,
            )

            def _add_jwt(context, callback):  # noqa: ANN001
                token = jwt_manager.get_token_or_none()
                metadata = [("authorization", f"Bearer {token}")] if token else []
                callback(metadata, None)

            call_creds = grpc.metadata_call_credentials(_add_jwt)
            credentials = grpc.composite_channel_credentials(ssl_creds, call_creds)
        else:
            # Development mode: plaintext
            log.warning("mTLS disabled — using plaintext gRPC (development only)")
            credentials = grpc.local_channel_credentials()

        otlp = OTLPMetricExporter(
            endpoint=cfg.otelcol_endpoint,
            credentials=credentials,
            compression=grpc.Compression.Gzip,
        )
        return cls(otlp, buffer)

    # ------------------------------------------------------------------
    # MetricExporter interface
    # ------------------------------------------------------------------

    @property
    def preferred_temporality(self):
        return self._otlp.preferred_temporality

    @property
    def preferred_aggregation(self):
        return self._otlp.preferred_aggregation

    def export(self, metrics_data: MetricsData, **kwargs) -> MetricExportResult:
        result = self._otlp.export(metrics_data, **kwargs)
        if result == MetricExportResult.SUCCESS:
            if not self._online:
                log.info("Collector back online")
                self._online = True
            return result

        # Collector unreachable — buffer the batch
        if self._online:
            log.warning("Collector unreachable, buffering metrics locally")
            self._online = False
        try:
            records = _metrics_data_to_records(metrics_data)
            self._buffer.write(records)
        except Exception as exc:
            log.error("Buffer write failed: %s", exc)
        # Return SUCCESS so the SDK doesn't discard future collections
        return MetricExportResult.SUCCESS

    def shutdown(self, timeout_millis: int = 30_000, **kwargs) -> None:
        self._otlp.shutdown(timeout_millis=timeout_millis, **kwargs)

    def force_flush(self, timeout_millis: int = 10_000) -> bool:
        return self._otlp.force_flush(timeout_millis=timeout_millis)


# ---------------------------------------------------------------------------
# Background replay task
# ---------------------------------------------------------------------------


async def buffer_replay_loop(
    exporter: OTLPMetricExporter,
    buffer: SQLiteBuffer,
    check_interval: int = 30,
) -> None:
    """Periodically drain buffered batches back to the Collector."""
    while True:
        await asyncio.sleep(check_interval)
        pending = buffer.pending_count()
        if pending == 0:
            continue

        log.info("Replaying %d buffered batch(es) …", pending)
        replayed = 0
        for batch_id, records in buffer.pending_batches():
            # Re-export the raw records via a simple OTLP JSON POST to HTTP endpoint
            # (full re-serialisation into OTel SDK objects is complex; we use the
            #  Telemetry Writer's REST fallback instead)
            try:
                import requests as req

                http_endpoint = exporter._endpoint.replace(":4317", ":4318")
                resp = req.post(
                    f"{http_endpoint}/v1/metrics/raw",
                    json=records,
                    timeout=10,
                )
                if resp.status_code < 300:
                    buffer.mark_replayed(batch_id)
                    replayed += 1
                else:
                    break  # still unreachable; try next cycle
            except Exception as exc:
                log.debug("Replay attempt failed: %s", exc)
                break

        if replayed:
            log.info("Replayed %d batch(es)", replayed)
