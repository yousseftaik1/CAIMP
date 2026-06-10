// Package natsgo provides a thin, typed NATS JetStream client for CAIMP v2 Go services.
//
// Usage:
//
//	c, err := natsgo.Connect(natsgo.ConfigFromEnv())
//	defer c.Drain()
//
//	err = c.Publish(natsgo.SubjectMetricReceived(orgID, serverID), payload)
//
//	sub, err := c.PullSubscribe("METRICS", "telemetry-writer", "metric.received.>")
//	msgs, err := sub.Fetch(100, nats.MaxWait(2*time.Second))
package natsgo

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"time"

	"github.com/nats-io/nats.go"
)

// ---------------------------------------------------------------------------
// Stream & subject names
// ---------------------------------------------------------------------------

const (
	StreamMetrics   = "METRICS"
	StreamAnomalies = "ANOMALIES"
	StreamAIOut     = "AI_OUT"
	StreamChat      = "CHAT"
	StreamAudit     = "AUDIT"
)

func SubjectMetricReceived(orgID, serverID string) string {
	return fmt.Sprintf("metric.received.%s.%s", orgID, serverID)
}

func SubjectAnomalyDetected(orgID, severity string) string {
	return fmt.Sprintf("anomaly.detected.%s.%s", orgID, severity)
}

func SubjectExplanationReady(orgID, incidentID string) string {
	return fmt.Sprintf("ai.explanation.ready.%s.%s", orgID, incidentID)
}

func SubjectExplanationFailed(orgID, incidentID string) string {
	return fmt.Sprintf("ai.explanation.failed.%s.%s", orgID, incidentID)
}

func SubjectChatRequested(orgID, sessionID string) string {
	return fmt.Sprintf("chat.requested.%s.%s", orgID, sessionID)
}

func SubjectAuditLog(action string) string {
	return fmt.Sprintf("audit.log.%s", action)
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

type Config struct {
	URL      string
	User     string
	Password string
}

func ConfigFromEnv() Config {
	return Config{
		URL:      envOr("NATS_URL", "nats://localhost:4222"),
		User:     os.Getenv("NATS_USER"),
		Password: os.Getenv("NATS_PASSWORD"),
	}
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

type Client struct {
	nc *nats.Conn
	js nats.JetStreamContext
}

func Connect(cfg Config) (*Client, error) {
	opts := []nats.Option{
		nats.MaxReconnects(-1),
		nats.ReconnectWait(2 * time.Second),
		nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {
			slog.Warn("NATS disconnected", "err", err)
		}),
		nats.ReconnectHandler(func(nc *nats.Conn) {
			slog.Info("NATS reconnected", "url", nc.ConnectedUrl())
		}),
	}

	if cfg.User != "" && cfg.Password != "" {
		opts = append(opts, nats.UserInfo(cfg.User, cfg.Password))
	}

	nc, err := nats.Connect(cfg.URL, opts...)
	if err != nil {
		return nil, fmt.Errorf("nats connect: %w", err)
	}

	js, err := nc.JetStream(nats.PublishAsyncMaxPending(256))
	if err != nil {
		nc.Close()
		return nil, fmt.Errorf("nats jetstream: %w", err)
	}

	slog.Info("Connected to NATS", "url", cfg.URL)
	return &Client{nc: nc, js: js}, nil
}

// Drain flushes pending messages and closes the connection gracefully.
func (c *Client) Drain() error {
	return c.nc.Drain()
}

// ---------------------------------------------------------------------------
// Publish
// ---------------------------------------------------------------------------

// Publish JSON-encodes v and publishes it to subject.
func (c *Client) Publish(subject string, v any) error {
	data, err := json.Marshal(v)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}
	ack, err := c.js.Publish(subject, data)
	if err != nil {
		return fmt.Errorf("publish to %s: %w", subject, err)
	}
	slog.Debug("Published", "subject", subject, "seq", ack.Sequence)
	return nil
}

// PublishAsync publishes without waiting for ACK (use for high-throughput paths).
func (c *Client) PublishAsync(subject string, v any) error {
	data, err := json.Marshal(v)
	if err != nil {
		return fmt.Errorf("marshal: %w", err)
	}
	if _, err := c.js.PublishAsync(subject, data); err != nil {
		return fmt.Errorf("publish async to %s: %w", subject, err)
	}
	return nil
}

// ---------------------------------------------------------------------------
// Subscribe (pull consumer)
// ---------------------------------------------------------------------------

// PullSubscribe creates or attaches to a durable pull consumer.
func (c *Client) PullSubscribe(stream, durableName, subjectFilter string) (*nats.Subscription, error) {
	sub, err := c.js.PullSubscribe(
		subjectFilter,
		durableName,
		nats.BindStream(stream),
		nats.AckWait(30*time.Second),
		nats.MaxDeliver(5),
	)
	if err != nil {
		return nil, fmt.Errorf("pull subscribe %s/%s: %w", stream, durableName, err)
	}
	return sub, nil
}

// ---------------------------------------------------------------------------
// Accessors for advanced use
// ---------------------------------------------------------------------------

func (c *Client) JS() nats.JetStreamContext { return c.js }
func (c *Client) NC() *nats.Conn            { return c.nc }
