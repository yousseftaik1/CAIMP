package receiver

import (
	"compress/gzip"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"time"

	"google.golang.org/protobuf/proto"

	commonpb "go.opentelemetry.io/proto/otlp/common/v1"
	collpb   "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	metpb    "go.opentelemetry.io/proto/otlp/metrics/v1"
	respb    "go.opentelemetry.io/proto/otlp/resource/v1"
)

// MetricPoint is a flattened metric data point ready for TimescaleDB.
type MetricPoint struct {
	Time       time.Time
	OrgID      string
	ServerID   string
	MetricName string
	Labels     map[string]string
	Value      float64
}

// Handler returns an http.Handler that receives OTLP metrics and calls onBatch.
func Handler(onBatch func(ctx context.Context, points []MetricPoint)) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/v1/metrics", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		body, err := readBody(r)
		if err != nil {
			slog.Error("Read body", "err", err)
			http.Error(w, "read error", http.StatusBadRequest)
			return
		}

		var req collpb.ExportMetricsServiceRequest
		ct := r.Header.Get("Content-Type")

		if ct == "application/json" {
			if err := json.Unmarshal(body, &req); err != nil {
				http.Error(w, "json decode: "+err.Error(), http.StatusBadRequest)
				return
			}
		} else {
			if err := proto.Unmarshal(body, &req); err != nil {
				http.Error(w, "proto decode: "+err.Error(), http.StatusBadRequest)
				return
			}
		}

		points := flatten(&req)
		if len(points) > 0 {
			onBatch(r.Context(), points)
		}

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{}`)) //nolint:errcheck
	})

	mux.HandleFunc("/v1/metrics/raw", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		body, err := readBody(r)
		if err != nil {
			http.Error(w, "read error", http.StatusBadRequest)
			return
		}
		var records []map[string]any
		if err := json.Unmarshal(body, &records); err != nil {
			http.Error(w, "json decode", http.StatusBadRequest)
			return
		}
		points := flattenRaw(records)
		if len(points) > 0 {
			onBatch(r.Context(), points)
		}
		w.WriteHeader(http.StatusOK)
	})

	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`)) //nolint:errcheck
	})

	return mux
}

// ---------------------------------------------------------------------------
// OTLP protobuf → MetricPoint
// ---------------------------------------------------------------------------

func flatten(req *collpb.ExportMetricsServiceRequest) []MetricPoint {
	var out []MetricPoint
	for _, rm := range req.ResourceMetrics {
		orgID, serverID := extractIDs(rm.Resource)
		if orgID == "" || serverID == "" {
			continue
		}
		for _, sm := range rm.ScopeMetrics {
			for _, m := range sm.Metrics {
				out = append(out, extractDataPoints(m, orgID, serverID)...)
			}
		}
	}
	return out
}

func extractIDs(res *respb.Resource) (orgID, serverID string) {
	if res == nil {
		return "", ""
	}
	for _, kv := range res.Attributes {
		switch kv.Key {
		case "caimp.org_id", "org.id":
			orgID = kv.Value.GetStringValue()
		case "caimp.server_id", "server.id", "host.id":
			serverID = kv.Value.GetStringValue()
		}
	}
	return
}

func extractDataPoints(m *metpb.Metric, orgID, serverID string) []MetricPoint {
	var pts []MetricPoint

	addPoint := func(t uint64, val float64, attrs []*commonpb.KeyValue) {
		ts := time.Unix(0, int64(t))
		if t == 0 {
			ts = time.Now()
		}
		labels := make(map[string]string, len(attrs))
		for _, kv := range attrs {
			labels[kv.Key] = kv.Value.GetStringValue()
		}
		pts = append(pts, MetricPoint{
			Time:       ts,
			OrgID:      orgID,
			ServerID:   serverID,
			MetricName: m.Name,
			Labels:     labels,
			Value:      val,
		})
	}

	switch data := m.Data.(type) {
	case *metpb.Metric_Gauge:
		for _, dp := range data.Gauge.DataPoints {
			addPoint(dp.TimeUnixNano, getNumberValue(dp), dp.Attributes)
		}
	case *metpb.Metric_Sum:
		for _, dp := range data.Sum.DataPoints {
			addPoint(dp.TimeUnixNano, getNumberValue(dp), dp.Attributes)
		}
	case *metpb.Metric_Histogram:
		for _, dp := range data.Histogram.DataPoints {
			var sum float64
			if dp.Sum != nil {
				sum = *dp.Sum
			}
			addPoint(dp.TimeUnixNano, sum, dp.Attributes)
		}
	}
	return pts
}

func getNumberValue(dp *metpb.NumberDataPoint) float64 {
	switch v := dp.Value.(type) {
	case *metpb.NumberDataPoint_AsDouble:
		return v.AsDouble
	case *metpb.NumberDataPoint_AsInt:
		return float64(v.AsInt)
	}
	return 0
}

// ---------------------------------------------------------------------------
// Raw JSON → MetricPoint (buffer replay)
// ---------------------------------------------------------------------------

func flattenRaw(records []map[string]any) []MetricPoint {
	var out []MetricPoint
	for _, rec := range records {
		name, _ := rec["name"].(string)
		resAttrs, _ := rec["resource_attributes"].(map[string]any)
		orgID, _ := resAttrs["caimp.org_id"].(string)
		if orgID == "" {
			orgID, _ = resAttrs["org.id"].(string)
		}
		serverID, _ := resAttrs["caimp.server_id"].(string)
		if serverID == "" {
			serverID, _ = resAttrs["server.id"].(string)
		}
		if serverID == "" {
			serverID, _ = resAttrs["host.id"].(string)
		}

		dps, _ := rec["data_points"].([]any)
		for _, rawDP := range dps {
			dp, ok := rawDP.(map[string]any)
			if !ok {
				continue
			}
			val, _ := dp["value"].(float64)
			attrs := map[string]string{}
			if a, ok := dp["attributes"].(map[string]any); ok {
				for k, v := range a {
					if s, ok := v.(string); ok {
						attrs[k] = s
					}
				}
			}
			var ts time.Time
			if nano, ok := dp["time_unix_nano"].(float64); ok && nano > 0 {
				ts = time.Unix(0, int64(nano))
			} else {
				ts = time.Now()
			}
			out = append(out, MetricPoint{
				Time:       ts,
				OrgID:      orgID,
				ServerID:   serverID,
				MetricName: name,
				Labels:     attrs,
				Value:      val,
			})
		}
	}
	return out
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

func readBody(r *http.Request) ([]byte, error) {
	var reader io.Reader = r.Body
	if r.Header.Get("Content-Encoding") == "gzip" {
		gz, err := gzip.NewReader(r.Body)
		if err != nil {
			return nil, err
		}
		defer gz.Close()
		reader = gz
	}
	return io.ReadAll(io.LimitReader(reader, 16*1024*1024))
}
