// CAIMP v2 — Telemetry Writer
//
// Receives OTLP/HTTP metric batches from the OTel Collector, persists them to
// TimescaleDB using bulk COPY, runs three anomaly detectors, and publishes
// events to NATS JetStream.
//
// Endpoints:
//   POST /v1/metrics        — OTLP protobuf or JSON
//   POST /v1/metrics/raw    — agent buffer replay (JSON records)
//   GET  /health            — liveness probe
//   GET  /metrics           — Prometheus scrape
package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/nats-io/nats.go"

	"github.com/caimp/telemetry-writer/internal/config"
	"github.com/caimp/telemetry-writer/internal/detector"
	"github.com/caimp/telemetry-writer/internal/metrics"
	"github.com/caimp/telemetry-writer/internal/publisher"
	"github.com/caimp/telemetry-writer/internal/receiver"
	"github.com/caimp/telemetry-writer/internal/writer"
)

func main() {
	setupLogging()

	cfg := config.Load()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// ---- PostgreSQL pool ------------------------------------------------
	pool, err := pgxpool.New(ctx, cfg.PostgresDSN)
	if err != nil {
		slog.Error("Postgres connect", "err", err)
		os.Exit(1)
	}
	defer pool.Close()
	waitPostgres(ctx, pool)

	// ---- NATS connection ------------------------------------------------
	nc, err := connectNATS(cfg)
	if err != nil {
		slog.Error("NATS connect", "err", err)
		os.Exit(1)
	}
	defer nc.Drain() //nolint:errcheck

	pub, err := publisher.New(nc)
	if err != nil {
		slog.Error("JetStream context", "err", err)
		os.Exit(1)
	}

	// ---- Pipeline -------------------------------------------------------
	pgWriter := writer.New(pool, cfg.BatchSize, cfg.BatchFlushSeconds)
	detPipeline := detector.New(pool, detector.Config{
		CPUThresholdPct:  cfg.CPUThresholdPct,
		RAMThresholdPct:  cfg.RAMThresholdPct,
		DiskThresholdPct: cfg.DiskThresholdPct,
		RateChangePct:    cfg.RateChangePct,
		ZScoreThreshold:  cfg.ZScoreThreshold,
	})

	onBatch := func(ctx context.Context, points []receiver.MetricPoint) {
		if len(points) == 0 {
			return
		}
		pgWriter.Add(points)

		// Group by org/server for METRICS stream signal
		serverBuckets := map[string]int{}
		for _, p := range points {
			serverBuckets[p.OrgID+"|"+p.ServerID]++
		}
		for key, count := range serverBuckets {
			parts := strings.SplitN(key, "|", 2)
			if len(parts) == 2 {
				pub.PublishMetricBatch(parts[0], parts[1], count)
			}
		}

		// Run detectors after write (use background ctx so detector queries
		// complete even if the HTTP request context is cancelled)
		go func(pts []receiver.MetricPoint) {
			events := detPipeline.Detect(context.Background(), pts)
			if len(events) == 0 {
				return
			}
			writer.PersistAnomalies(context.Background(), pool, events)
			for _, ev := range events {
				pub.PublishAnomaly(ev)
				slog.Info("Anomaly detected",
					"detector", ev.Detector,
					"metric", ev.MetricName,
					"server", ev.ServerID,
					"severity", ev.Severity,
				)
			}
		}(points)
	}

	// ---- HTTP servers ---------------------------------------------------
	// Metrics writer server
	mux := receiver.Handler(onBatch)
	writerSrv := &http.Server{
		Addr:         cfg.ListenAddr,
		Handler:      mux,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
	}

	// Prometheus metrics server
	metricsMux := http.NewServeMux()
	metricsMux.Handle("/metrics", metrics.Handler())
	metricsSrv := &http.Server{
		Addr:    cfg.MetricsAddr,
		Handler: metricsMux,
	}

	// ---- Start ----------------------------------------------------------
	go func() {
		if err := writerSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("Writer server", "err", err)
			cancel()
		}
	}()
	go func() {
		if err := metricsSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("Metrics server", "err", err)
		}
	}()
	go pgWriter.Run(ctx)

	slog.Info("Telemetry Writer started",
		"listen", cfg.ListenAddr,
		"metrics", cfg.MetricsAddr,
	)

	// ---- Graceful shutdown ----------------------------------------------
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	slog.Info("Shutting down …")
	cancel()

	shutCtx, shutCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutCancel()
	writerSrv.Shutdown(shutCtx)  //nolint:errcheck
	metricsSrv.Shutdown(shutCtx) //nolint:errcheck
	slog.Info("Telemetry Writer stopped")
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func setupLogging() {
	level := slog.LevelInfo
	if os.Getenv("LOG_LEVEL") == "DEBUG" {
		level = slog.LevelDebug
	}
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: level})))
}

func waitPostgres(ctx context.Context, pool *pgxpool.Pool) {
	for i := 0; i < 30; i++ {
		if err := pool.Ping(ctx); err == nil {
			slog.Info("PostgreSQL connected")
			return
		}
		slog.Info("Waiting for PostgreSQL …", "attempt", i+1)
		time.Sleep(2 * time.Second)
	}
	slog.Error("PostgreSQL not ready after 60s — exiting")
	os.Exit(1)
}

func connectNATS(cfg *config.Config) (*nats.Conn, error) {
	opts := []nats.Option{
		nats.MaxReconnects(-1),
		nats.ReconnectWait(2 * time.Second),
		nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {
			slog.Warn("NATS disconnected", "err", err)
		}),
	}
	if cfg.NatsUser != "" {
		opts = append(opts, nats.UserInfo(cfg.NatsUser, cfg.NatsPassword))
	}
	return nats.Connect(cfg.NatsURL, opts...)
}
