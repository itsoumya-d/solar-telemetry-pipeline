# Operational Runbook: Solar Telemetry Pipeline

## 1. Overview & Service Objectives
The Solar Telemetry Pipeline ingests high-frequency solar inverter readings, performs schema validation, enforces deduplication/idempotency, executes sliding-window anomaly detection, and runs end-of-period billing reconciliation.

- **Target Availability (SLO):** 99.9% uptime for `/health` and `/ingest`.
- **Latency SLO:** p95 latency < 45ms, p99 latency < 120ms under 500 req/s.

## 2. Health & Monitoring
- **Health Check Endpoint:** `GET /health` (returns `{"status": "ok"}`)
- **Readiness Verification:** Ensure port 8000 is open and listening.
- **Log Monitoring:** Look for dead-letter spikes (`rejected > 0`) or malformed payload rejections (`HTTP 422`).

## 3. Incident Troubleshooting

### 3.1 High Rejection / Dead-Letter Ingestion Rate
1. Check `/ingest` response summary: review `dead_letters` array for specific validation error reasons.
2. Verify timestamp formats (`ISO-8601 UTC`).
3. Verify telemetry readings: power and energy metrics must not be negative or exceed inverter capacity thresholds.

### 3.2 Service Stalls or Memory Growth
1. Inspect container memory usage and active workers.
2. Restart uvicorn worker pool: `pkill -HUP uvicorn` or restart the systemd service / container replica.

## 4. Rollback Procedure
If a deployment exhibits regressions (e.g. failing health checks or increased error rates):
1. Immediately stop incoming traffic to the degraded deployment by switching DNS or load-balancer target to the previous release.
2. For container/k8s rollouts:
   ```bash
   kubectl rollout undo deployment/solarpipe-api
   ```
3. For standalone server installations:
   ```bash
   git checkout tags/<previous-stable-tag>
   pip install -e .
   systemctl restart solarpipe
   ```
4. Run the automated smoke test to verify system stability:
   ```bash
   ./scripts/smoke.sh
   ```
5. Confirm rollback success via `GET /health` and post-incident review within 24 hours.
