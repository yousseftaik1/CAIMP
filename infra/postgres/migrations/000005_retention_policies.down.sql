SELECT remove_compression_policy('metrics_5m', if_exists => true);
SELECT remove_compression_policy('metrics', if_exists => true);
SELECT remove_retention_policy('metrics_5m', if_exists => true);
SELECT remove_retention_policy('metrics', if_exists => true);
