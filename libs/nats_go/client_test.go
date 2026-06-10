package natsgo_test

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"

	natsgo "github.com/caimp/libs/nats_go"
)

// ---------------------------------------------------------------------------
// Unit tests — no NATS required
// ---------------------------------------------------------------------------

func TestSubjectHelpers(t *testing.T) {
	tests := []struct {
		name string
		got  string
		want string
	}{
		{"MetricReceived", natsgo.SubjectMetricReceived("org1", "srv1"), "metric.received.org1.srv1"},
		{"AnomalyDetected", natsgo.SubjectAnomalyDetected("org1", "critical"), "anomaly.detected.org1.critical"},
		{"ExplanationReady", natsgo.SubjectExplanationReady("org1", "inc42"), "ai.explanation.ready.org1.inc42"},
		{"ExplanationFailed", natsgo.SubjectExplanationFailed("org1", "inc42"), "ai.explanation.failed.org1.inc42"},
		{"ChatRequested", natsgo.SubjectChatRequested("org1", "sess1"), "chat.requested.org1.sess1"},
		{"AuditLog", natsgo.SubjectAuditLog("user.created"), "audit.log.user.created"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if tc.got != tc.want {
				t.Errorf("got %q, want %q", tc.got, tc.want)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Integration tests — require a live NATS at NATS_URL
// Run: go test -tags integration ./...
// ---------------------------------------------------------------------------

//go:build integration

type anomalyPayload struct {
	IncidentID string    `json:"incident_id"`
	OrgID      string    `json:"org_id"`
	ServerID   string    `json:"server_id"`
	MetricName string    `json:"metric_name"`
	Value      float64   `json:"value"`
	Detector   string    `json:"detector"`
	Severity   string    `json:"severity"`
	Timestamp  time.Time `json:"timestamp"`
}

func TestPublishAndConsumeRoundtrip(t *testing.T) {
	cfg := natsgo.ConfigFromEnv()
	c, err := natsgo.Connect(cfg)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer c.Drain()

	orgID    := fmt.Sprintf("test-org-%d", time.Now().UnixNano())
	incident := fmt.Sprintf("inc-%d", time.Now().UnixNano())
	subject  := natsgo.SubjectAnomalyDetected(orgID, "warning")

	payload := anomalyPayload{
		IncidentID: incident,
		OrgID:      orgID,
		ServerID:   "srv-test",
		MetricName: "cpu_usage",
		Value:      92.5,
		Detector:   "static",
		Severity:   "warning",
		Timestamp:  time.Now().UTC(),
	}

	if err := c.Publish(subject, payload); err != nil {
		t.Fatalf("publish: %v", err)
	}

	durableName := fmt.Sprintf("go-test-%d", time.Now().UnixNano())
	sub, err := c.PullSubscribe(natsgo.StreamAnomalies, durableName, subject)
	if err != nil {
		t.Fatalf("pull subscribe: %v", err)
	}

	msgs, err := sub.Fetch(1, nats.MaxWait(5*time.Second))
	if err != nil || len(msgs) == 0 {
		t.Fatalf("fetch: %v (msgs=%d)", err, len(msgs))
	}

	var got anomalyPayload
	if err := json.Unmarshal(msgs[0].Data, &got); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if got.IncidentID != incident {
		t.Errorf("incident_id: got %q, want %q", got.IncidentID, incident)
	}

	msgs[0].Ack()
}
