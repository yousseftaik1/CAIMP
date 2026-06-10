package config

import (
	"os"
	"strconv"
)

type Config struct {
	PostgresDSN       string
	NatsURL           string
	NatsUser          string
	NatsPassword      string
	ListenAddr        string
	MetricsAddr       string
	BatchSize         int
	BatchFlushSeconds int
	CPUThresholdPct   float64
	RAMThresholdPct   float64
	DiskThresholdPct  float64
	RateChangePct     float64
	ZScoreThreshold   float64
}

func Load() *Config {
	return &Config{
		PostgresDSN:       getEnv("POSTGRES_DSN", ""),
		NatsURL:           getEnv("NATS_URL", "nats://localhost:4222"),
		NatsUser:          getEnv("NATS_USER", ""),
		NatsPassword:      getEnv("NATS_PASSWORD", ""),
		ListenAddr:        getEnv("LISTEN_ADDR", ":4318"),
		MetricsAddr:       getEnv("METRICS_ADDR", ":9091"),
		BatchSize:         getEnvInt("BATCH_SIZE", 2000),
		BatchFlushSeconds: getEnvInt("BATCH_FLUSH_SECONDS", 5),
		CPUThresholdPct:   getEnvFloat("CPU_THRESHOLD_PCT", 90),
		RAMThresholdPct:   getEnvFloat("RAM_THRESHOLD_PCT", 90),
		DiskThresholdPct:  getEnvFloat("DISK_THRESHOLD_PCT", 85),
		RateChangePct:     getEnvFloat("RATE_CHANGE_PCT", 20),
		ZScoreThreshold:   getEnvFloat("ZSCORE_THRESHOLD", 3.0),
	}
}

func getEnv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getEnvInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func getEnvFloat(key string, def float64) float64 {
	if v := os.Getenv(key); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return def
}
