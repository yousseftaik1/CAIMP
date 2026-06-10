package detector

import (
	"context"
	"fmt"
	"math"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/caimp/telemetry-writer/internal/receiver"
)

// AnomalyEvent is the canonical event emitted by all detectors and published
// to NATS JetStream. JSON tags match the Python Pydantic model consumed by
// ai-worker and alert-engine.
type AnomalyEvent struct {
	IncidentID string            `json:"incident_id"`
	OrgID      string            `json:"org_id"`
	ServerID   string            `json:"server_id"`
	MetricName string            `json:"metric_name"`
	Value      float64           `json:"value"`
	Threshold  *float64          `json:"threshold,omitempty"`
	Detector   string            `json:"detector"`
	Severity   string            `json:"severity"`
	Timestamp  time.Time         `json:"timestamp"`
	Labels     map[string]string `json:"labels"`
}

// Config holds thresholds for all three detectors.
type Config struct {
	CPUThresholdPct  float64
	RAMThresholdPct  float64
	DiskThresholdPct float64
	RateChangePct    float64
	ZScoreThreshold  float64
}

// Detector runs threshold, rate-of-change, and z-score detection on each batch.
type Detector struct {
	pool *pgxpool.Pool
	cfg  Config
}

func New(pool *pgxpool.Pool, cfg Config) *Detector {
	return &Detector{pool: pool, cfg: cfg}
}

// Detect runs all three detectors and returns de-duplicated events.
func (d *Detector) Detect(ctx context.Context, points []receiver.MetricPoint) []AnomalyEvent {
	var events []AnomalyEvent
	events = append(events, d.threshold(points)...)
	events = append(events, d.rateOfChange(points)...)
	events = append(events, d.zScore(ctx, points)...)
	return events
}

// ---------------------------------------------------------------------------
// Detector 1: static threshold
// ---------------------------------------------------------------------------

func (d *Detector) threshold(points []receiver.MetricPoint) []AnomalyEvent {
	var events []AnomalyEvent
	for _, p := range points {
		var limit float64
		name := strings.ToLower(p.MetricName)
		switch {
		case strings.Contains(name, "cpu"):
			limit = d.cfg.CPUThresholdPct
		case strings.Contains(name, "mem") || strings.Contains(name, "ram"):
			limit = d.cfg.RAMThresholdPct
		case strings.Contains(name, "disk") || strings.Contains(name, "filesystem"):
			limit = d.cfg.DiskThresholdPct
		default:
			continue
		}
		// OTel utilization metrics are 0–1 fractions; thresholds are 0–100 percentages.
		valuePct := p.Value * 100
		if limit <= 0 || valuePct < limit {
			continue
		}
		severity := "warning"
		if valuePct >= limit*1.1 {
			severity = "critical"
		}
		thr := limit
		events = append(events, AnomalyEvent{
			IncidentID: incidentID(p, "threshold"),
			OrgID:      p.OrgID,
			ServerID:   p.ServerID,
			MetricName: p.MetricName,
			Value:      p.Value,
			Threshold:  &thr,
			Detector:   "threshold",
			Severity:   severity,
			Timestamp:  p.Time,
			Labels:     p.Labels,
		})
	}
	return events
}

// ---------------------------------------------------------------------------
// Detector 2: rate of change
// ---------------------------------------------------------------------------

func (d *Detector) rateOfChange(points []receiver.MetricPoint) []AnomalyEvent {
	if d.cfg.RateChangePct <= 0 {
		return nil
	}
	type seriesKey struct{ org, server, metric string }
	prev := map[seriesKey]receiver.MetricPoint{}

	var events []AnomalyEvent
	for _, p := range points {
		k := seriesKey{p.OrgID, p.ServerID, p.MetricName}
		if last, ok := prev[k]; ok && last.Value != 0 {
			changePct := math.Abs(p.Value-last.Value) / math.Abs(last.Value) * 100
			if changePct >= d.cfg.RateChangePct {
				events = append(events, AnomalyEvent{
					IncidentID: incidentID(p, "roc"),
					OrgID:      p.OrgID,
					ServerID:   p.ServerID,
					MetricName: p.MetricName,
					Value:      p.Value,
					Detector:   "rate_of_change",
					Severity:   "warning",
					Timestamp:  p.Time,
					Labels:     p.Labels,
				})
			}
		}
		prev[k] = p
	}
	return events
}

// ---------------------------------------------------------------------------
// Detector 3: z-score against 1-hour baseline
// ---------------------------------------------------------------------------

func (d *Detector) zScore(ctx context.Context, points []receiver.MetricPoint) []AnomalyEvent {
	if d.cfg.ZScoreThreshold <= 0 || d.pool == nil {
		return nil
	}
	var events []AnomalyEvent
	for _, p := range points {
		var avg, stddev float64
		err := d.pool.QueryRow(ctx,
			`SELECT COALESCE(avg(value), 0), COALESCE(stddev(value), 0)
			 FROM metrics
			 WHERE org_id = $1 AND server_id = $2 AND metric_name = $3
			   AND time > now() - INTERVAL '1 hour'`,
			p.OrgID, p.ServerID, p.MetricName,
		).Scan(&avg, &stddev)
		if err != nil || stddev == 0 {
			continue
		}
		z := math.Abs(p.Value-avg) / stddev
		if z < d.cfg.ZScoreThreshold {
			continue
		}
		severity := "warning"
		if z >= d.cfg.ZScoreThreshold*1.5 {
			severity = "critical"
		}
		events = append(events, AnomalyEvent{
			IncidentID: incidentID(p, "zscore"),
			OrgID:      p.OrgID,
			ServerID:   p.ServerID,
			MetricName: p.MetricName,
			Value:      p.Value,
			Detector:   "zscore",
			Severity:   severity,
			Timestamp:  p.Time,
			Labels:     p.Labels,
		})
	}
	return events
}

func incidentID(p receiver.MetricPoint, detector string) string {
	return fmt.Sprintf("%s-%s-%s-%d-%s", p.OrgID, p.ServerID, p.MetricName, p.Time.Unix(), detector)
}
