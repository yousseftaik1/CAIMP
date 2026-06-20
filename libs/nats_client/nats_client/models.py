"""Typed message models and subject/stream name constants."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Streams:
    METRICS = "METRICS"
    ANOMALIES = "ANOMALIES"
    AI_OUT = "AI_OUT"
    CHAT = "CHAT"
    AUDIT = "AUDIT"


class Subjects:
    @staticmethod
    def metric_received(org_id: str | UUID, server_id: str | UUID) -> str:
        return f"metric.received.{org_id}.{server_id}"

    @staticmethod
    def anomaly_detected(org_id: str | UUID, severity: str) -> str:
        return f"anomaly.detected.{org_id}.{severity}"

    @staticmethod
    def explanation_ready(org_id: str | UUID, incident_id: str) -> str:
        return f"ai.explanation.ready.{org_id}.{incident_id}"

    @staticmethod
    def explanation_failed(org_id: str | UUID, incident_id: str) -> str:
        return f"ai.explanation.failed.{org_id}.{incident_id}"

    @staticmethod
    def chat_requested(org_id: str | UUID, session_id: str) -> str:
        return f"chat.requested.{org_id}.{session_id}"

    @staticmethod
    def audit_log(action: str) -> str:
        return f"audit.log.{action}"

    @staticmethod
    def forecast_critical(org_id: str | UUID, server_id: str | UUID) -> str:
        return f"forecast.critical.{org_id}.{server_id}"

    @staticmethod
    def forecast_evaluated(org_id: str | UUID, server_id: str | UUID) -> str:
        return f"forecast.evaluated.{org_id}.{server_id}"


# ---------------------------------------------------------------------------
# Message payloads
# ---------------------------------------------------------------------------


class MetricBatch(BaseModel):
    org_id: str
    server_id: str
    timestamp: datetime
    metrics: list[dict[str, Any]]


class AnomalyEvent(BaseModel):
    incident_id: str
    org_id: str
    server_id: str
    metric_name: str
    value: float
    threshold: float | None = None
    detector: str  # static | rate_of_change | zscore
    severity: str  # warning | critical
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    labels: dict[str, str] = {}


class ExplanationReady(BaseModel):
    incident_id: str
    org_id: str
    server_id: str
    severity: str
    explanation: str
    root_cause: str | None = None
    recommended_action: str | None = None
    confidence: str  # low | medium | high
    model: str
    cached: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatRequest(BaseModel):
    session_id: str
    org_id: str
    user_id: str
    message: str
    history: list[dict[str, str]] = []


class AuditEvent(BaseModel):
    org_id: str | None = None
    actor_id: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    details: dict[str, Any] = {}
    ip_address: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ForecastCritical(BaseModel):
    forecast_id: str
    org_id: str
    server_id: str
    metric_name: str
    time_to_critical: float  # hours until threshold breach
    current_trend_slope: float  # units per hour
    critical_threshold: float
    llm_narrative: str | None = None
    llm_confidence: str | None = None  # low | medium | high
    forecasted_at: datetime = Field(default_factory=datetime.utcnow)
