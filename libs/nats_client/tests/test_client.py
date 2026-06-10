"""
Unit + integration tests for the Python NATS client helper.

Integration tests (marked with @pytest.mark.integration) require a live NATS
instance at NATS_URL (default: nats://localhost:4222).  Run:

    docker compose up nats -d
    pytest libs/nats_client/tests/ -m integration
"""

import asyncio
from datetime import datetime
from uuid import uuid4

import pytest

from nats_client.models import (
    AnomalyEvent,
    ExplanationReady,
    Streams,
    Subjects,
)


# ---------------------------------------------------------------------------
# Unit tests — no NATS required
# ---------------------------------------------------------------------------

class TestSubjects:
    def test_metric_received(self):
        s = Subjects.metric_received("org-1", "srv-1")
        assert s == "metric.received.org-1.srv-1"

    def test_anomaly_detected(self):
        s = Subjects.anomaly_detected("org-1", "critical")
        assert s == "anomaly.detected.org-1.critical"

    def test_explanation_ready(self):
        s = Subjects.explanation_ready("org-1", "inc-42")
        assert s == "ai.explanation.ready.org-1.inc-42"

    def test_chat_requested(self):
        s = Subjects.chat_requested("org-1", "sess-abc")
        assert s == "chat.requested.org-1.sess-abc"

    def test_audit_log(self):
        s = Subjects.audit_log("user.created")
        assert s == "audit.log.user.created"


class TestModels:
    def test_anomaly_event_roundtrip(self):
        ev = AnomalyEvent(
            incident_id="inc-1",
            org_id=str(uuid4()),
            server_id=str(uuid4()),
            metric_name="cpu_usage",
            value=95.5,
            threshold=90.0,
            detector="static",
            severity="critical",
            timestamp=datetime.utcnow(),
        )
        json_str = ev.model_dump_json()
        ev2 = AnomalyEvent.model_validate_json(json_str)
        assert ev2.incident_id == ev.incident_id
        assert ev2.value == ev.value

    def test_explanation_ready_roundtrip(self):
        ex = ExplanationReady(
            incident_id="inc-1",
            org_id=str(uuid4()),
            server_id=str(uuid4()),
            severity="critical",
            explanation="CPU saturation detected.",
            confidence="high",
            model="llama3.1:8b",
        )
        json_str = ex.model_dump_json()
        ex2 = ExplanationReady.model_validate_json(json_str)
        assert ex2.confidence == "high"
        assert ex2.cached is False


# ---------------------------------------------------------------------------
# Integration tests — require live NATS
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestNatsClientIntegration:
    @pytest.fixture
    def event_loop(self):
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    @pytest.mark.asyncio
    async def test_publish_and_consume_roundtrip(self):
        from nats_client.client import NatsClient
        from nats_client.models import AnomalyEvent

        org_id    = str(uuid4())
        server_id = str(uuid4())
        incident  = str(uuid4())

        event = AnomalyEvent(
            incident_id=incident,
            org_id=org_id,
            server_id=server_id,
            metric_name="ram_used_pct",
            value=92.0,
            detector="static",
            severity="warning",
            timestamp=datetime.utcnow(),
        )

        async with NatsClient.connect() as nc:
            subject = Subjects.anomaly_detected(org_id, "warning")
            await nc.publish(subject, event)

            # Consume from ANOMALIES stream
            result = await nc.fetch_one(
                stream=Streams.ANOMALIES,
                consumer_name=f"test-{uuid4()}",
                model=AnomalyEvent,
                subject_filter=subject,
            )
            assert result is not None
            fetched_event, msg = result
            assert fetched_event.incident_id == incident
            await msg.ack()

    @pytest.mark.asyncio
    async def test_durability_across_reconnect(self):
        """Message published before consumer exists is still deliverable."""
        from nats_client.client import NatsClient
        from nats_client.models import AnomalyEvent

        org_id   = str(uuid4())
        incident = str(uuid4())
        subject  = Subjects.anomaly_detected(org_id, "critical")
        consumer = f"durable-test-{uuid4()}"

        event = AnomalyEvent(
            incident_id=incident,
            org_id=org_id,
            server_id=str(uuid4()),
            metric_name="cpu_usage",
            value=99.0,
            detector="static",
            severity="critical",
            timestamp=datetime.utcnow(),
        )

        # Publish without an active consumer
        async with NatsClient.connect() as nc:
            await nc.publish(subject, event)

        # Reconnect and consume — message must still be there
        async with NatsClient.connect() as nc:
            result = await nc.fetch_one(
                stream=Streams.ANOMALIES,
                consumer_name=consumer,
                model=AnomalyEvent,
                subject_filter=subject,
            )
            assert result is not None
            fetched, msg = result
            assert fetched.incident_id == incident
            await msg.ack()
