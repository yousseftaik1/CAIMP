package metrics

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	BatchesTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "caimp_telemetry_batches_total",
		Help: "Total metric batches written to Postgres.",
	})
	MetricsTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "caimp_telemetry_metrics_total",
		Help: "Total individual metric points written.",
	})
	AnomaliesTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "caimp_anomalies_detected_total",
		Help: "Anomalies detected by detector type.",
	}, []string{"detector"})
	WriteLatency = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "caimp_write_duration_seconds",
		Help:    "Postgres COPY duration.",
		Buckets: prometheus.DefBuckets,
	})
)

func Handler() http.Handler {
	return promhttp.Handler()
}
