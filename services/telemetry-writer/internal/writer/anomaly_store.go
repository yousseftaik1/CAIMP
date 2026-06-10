package writer

import (
	"context"
	"log/slog"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/caimp/telemetry-writer/internal/detector"
)

// PersistAnomalies inserts detected anomaly events into anomaly_events so the
// query API and AI worker can join them by incident_id.
func PersistAnomalies(ctx context.Context, pool *pgxpool.Pool, events []detector.AnomalyEvent) {
	for _, ev := range events {
		_, err := pool.Exec(ctx,
			`INSERT INTO anomaly_events
			     (org_id, server_id, metric_name, value, threshold,
			      detector, severity, incident_id, time)
			 VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9)
			 ON CONFLICT DO NOTHING`,
			ev.OrgID, ev.ServerID, ev.MetricName, ev.Value, ev.Threshold,
			ev.Detector, ev.Severity, ev.IncidentID, ev.Timestamp,
		)
		if err != nil {
			slog.Warn("Failed to persist anomaly event",
				"incident_id", ev.IncidentID, "err", err)
		}
	}
}
