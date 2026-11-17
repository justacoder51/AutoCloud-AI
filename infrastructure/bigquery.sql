-- Run only after review/approval. Target project and region are user-confirmed.
CREATE SCHEMA IF NOT EXISTS `astute-sign-506809-j8.autocloud`
OPTIONS(location = 'asia-south1');

CREATE TABLE IF NOT EXISTS `astute-sign-506809-j8.autocloud.infrastructure_metrics` (
  timestamp TIMESTAMP NOT NULL,
  collected_at TIMESTAMP NOT NULL,
  record_id STRING NOT NULL,
  project_id STRING NOT NULL,
  region STRING NOT NULL,
  service_name STRING NOT NULL,
  source STRING NOT NULL,
  interval_seconds INT64 NOT NULL,
  cpu_utilization FLOAT64,
  memory_utilization FLOAT64,
  request_count INT64,
  network_ingress INT64,
  network_egress INT64,
  average_latency FLOAT64,
  error_rate FLOAT64,
  instance_count FLOAT64,
  missing_fields ARRAY<STRING>
)
PARTITION BY DATE(timestamp)
CLUSTER BY service_name
OPTIONS(require_partition_filter = TRUE, partition_expiration_days = 30);

-- Loads are append-only. Use this view to avoid counting overlapping polls twice.
-- The partition predicate bounds reads and satisfies require_partition_filter.
CREATE OR REPLACE VIEW `astute-sign-506809-j8.autocloud.latest_metrics` AS
SELECT *
FROM `astute-sign-506809-j8.autocloud.infrastructure_metrics`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY record_id ORDER BY collected_at DESC
) = 1;
