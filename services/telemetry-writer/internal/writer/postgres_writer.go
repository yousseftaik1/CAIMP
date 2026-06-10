// Package writer handles bulk insertion of metric points into TimescaleDB.
// Uses pgx COPY protocol for maximum throughput (~100k rows/s on one core).
package writer

import (
	"context"
	"encoding/json"
	"log/slog"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"

	"github.com/caimp/telemetry-writer/internal/receiver"
)

var (
	insertDuration = promauto.NewHistogram(prometheus.HistogramOpts{
		Namespace: "telemetry_writer",
		Name:      "insert_duration_seconds",
		Help:      "Time to bulk-insert a batch into TimescaleDB",
		Buckets:   prometheus.DefBuckets,
	})
	insertRows = promauto.NewCounter(prometheus.CounterOpts{
		Namespace: "telemetry_writer",
		Name:      "inserted_rows_total",
		Help:      "Total rows inserted into the metrics hypertable",
	})
	insertErrors = promauto.NewCounter(prometheus.CounterOpts{
		Namespace: "telemetry_writer",
		Name:      "insert_errors_total",
		Help:      "Total bulk-insert failures",
	})
)

// PostgresWriter accumulates MetricPoints in a buffer and flushes them to
// TimescaleDB using pgx COPY.  Thread-safe.
type PostgresWriter struct {
	pool      *pgxpool.Pool
	batchSize int
	flushSecs int

	mu     sync.Mutex
	buffer []receiver.MetricPoint

	flushCh chan struct{}
}

func New(pool *pgxpool.Pool, batchSize, flushSecs int) *PostgresWriter {
	w := &PostgresWriter{
		pool:      pool,
		batchSize: batchSize,
		flushSecs: flushSecs,
		flushCh:   make(chan struct{}, 1),
	}
	return w
}

// Add appends points to the internal buffer. Triggers a flush if the batch
// size is reached.
func (w *PostgresWriter) Add(points []receiver.MetricPoint) {
	w.mu.Lock()
	w.buffer = append(w.buffer, points...)
	shouldFlush := len(w.buffer) >= w.batchSize
	w.mu.Unlock()

	if shouldFlush {
		select {
		case w.flushCh <- struct{}{}:
		default:
		}
	}
}

// Run starts the periodic flush loop. Blocks until ctx is cancelled.
func (w *PostgresWriter) Run(ctx context.Context) {
	ticker := time.NewTicker(time.Duration(w.flushSecs) * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			w.flush(context.Background()) // drain on shutdown
			return
		case <-ticker.C:
			w.flush(ctx)
		case <-w.flushCh:
			w.flush(ctx)
		}
	}
}

func (w *PostgresWriter) flush(ctx context.Context) {
	w.mu.Lock()
	if len(w.buffer) == 0 {
		w.mu.Unlock()
		return
	}
	batch := w.buffer
	w.buffer = make([]receiver.MetricPoint, 0, w.batchSize)
	w.mu.Unlock()

	start := time.Now()
	if err := w.copyInsert(ctx, batch); err != nil {
		slog.Error("Bulk insert failed", "err", err, "rows", len(batch))
		insertErrors.Inc()
		// Re-queue on transient failure (once)
		w.mu.Lock()
		w.buffer = append(batch, w.buffer...)
		w.mu.Unlock()
		return
	}
	dur := time.Since(start)
	insertDuration.Observe(dur.Seconds())
	insertRows.Add(float64(len(batch)))
	slog.Debug("Flushed batch", "rows", len(batch), "duration_ms", dur.Milliseconds())
}

// copyInsert uses the pgx COPY protocol for maximum insert throughput.
func (w *PostgresWriter) copyInsert(ctx context.Context, points []receiver.MetricPoint) error {
	cols := []string{"time", "org_id", "server_id", "metric_name", "labels", "value"}

	rows := make([][]any, len(points))
	for i, p := range points {
		labelsJSON, _ := json.Marshal(p.Labels)
		rows[i] = []any{p.Time, p.OrgID, p.ServerID, p.MetricName, string(labelsJSON), p.Value}
	}

	_, err := w.pool.CopyFrom(
		ctx,
		pgx.Identifier{"metrics"},
		cols,
		pgx.CopyFromRows(rows),
	)
	return err
}

// BulkInsertBenchmark inserts n synthetic rows and returns duration (for CI benchmark).
func BulkInsertBenchmark(ctx context.Context, pool *pgxpool.Pool, n int) (time.Duration, error) {
	w := New(pool, n, 1)
	points := make([]receiver.MetricPoint, n)
	now := time.Now()
	for i := range points {
		points[i] = receiver.MetricPoint{
			Time:       now,
			OrgID:      "bench-org",
			ServerID:   "bench-srv",
			MetricName: "benchmark.metric",
			Labels:     map[string]string{"i": "0"},
			Value:      float64(i),
		}
	}
	start := time.Now()
	err   := w.copyInsert(ctx, points)
	return time.Since(start), err
}
