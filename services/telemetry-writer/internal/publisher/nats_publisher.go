// Package publisher publishes metric and anomaly events to NATS JetStream.
package publisher

import (
	"encoding/json"
	"fmt"
	"log/slog"

	"github.com/nats-io/nats.go"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"

	"github.com/caimp/telemetry-writer/internal/detector"
)

var publishErrors = promauto.NewCounterVec(prometheus.CounterOpts{
	Namespace: "telemetry_writer",
	Name:      "nats_publish_errors_total",
	Help:      "NATS publish failures by subject prefix",
}, []string{"stream"})

// Publisher wraps a NATS JetStream context.
type Publisher struct {
	js nats.JetStreamContext
}

func New(nc *nats.Conn) (*Publisher, error) {
	js, err := nc.JetStream(nats.PublishAsyncMaxPending(512))
	if err != nil {
		return nil, fmt.Errorf("jetstream context: %w", err)
	}
	return &Publisher{js: js}, nil
}

// PublishAnomaly sends an AnomalyEvent to ANOMALIES.{org_id}.{severity}.
func (p *Publisher) PublishAnomaly(ev detector.AnomalyEvent) {
	subject := fmt.Sprintf("anomaly.detected.%s.%s", ev.OrgID, ev.Severity)
	p.publish(subject, "ANOMALIES", ev)
}

// PublishMetricBatch signals that a batch of metrics was received for an org/server.
// Consumers (Alert Engine) can use this for threshold-rule evaluation.
func (p *Publisher) PublishMetricBatch(orgID, serverID string, count int) {
	subject := fmt.Sprintf("metric.received.%s.%s", orgID, serverID)
	payload := map[string]any{
		"org_id":    orgID,
		"server_id": serverID,
		"count":     count,
	}
	p.publish(subject, "METRICS", payload)
}

func (p *Publisher) publish(subject, stream string, payload any) {
	data, err := json.Marshal(payload)
	if err != nil {
		slog.Error("Marshal payload", "err", err, "subject", subject)
		return
	}
	if _, err := p.js.PublishAsync(subject, data); err != nil {
		slog.Warn("NATS publish failed", "subject", subject, "err", err)
		publishErrors.WithLabelValues(stream).Inc()
	}
}
