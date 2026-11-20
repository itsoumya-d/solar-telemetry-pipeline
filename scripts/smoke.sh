#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
BASE_URL="http://${HOST}:${PORT}"

echo "Starting smoke test against ${BASE_URL}..."

# Wait for service to become responsive (up to 15s)
MAX_RETRIES=15
COUNT=0
until curl -s -f "${BASE_URL}/health" > /dev/null || [ "$COUNT" -ge "$MAX_RETRIES" ]; do
  sleep 1
  COUNT=$((COUNT + 1))
done

if [ "$COUNT" -ge "$MAX_RETRIES" ]; then
  echo "Smoke test failure: Service at ${BASE_URL} failed to start in time."
  exit 1
fi

HEALTH_RESP=$(curl -s "${BASE_URL}/health")
echo "Health check response: ${HEALTH_RESP}"
if [[ "$HEALTH_RESP" != *"ok"* ]]; then
  echo "Smoke test failure: Health endpoint did not return expected status."
  exit 1
fi

echo "Testing site registration endpoint..."
SITE_RESP=$(curl -s -X POST "${BASE_URL}/sites" \
  -H "Content-Type: application/json" \
  -d '{"site_id": "smoke-test-site", "capacity_kw": "100.0", "inverter_ids": ["inv-1", "inv-2"], "interval_minutes": 5}')

echo "Site registration response: ${SITE_RESP}"
if [[ "$SITE_RESP" != *"registered"* ]]; then
  echo "Smoke test failure: /sites failed to register site."
  exit 1
fi

echo "Smoke test PASSED successfully."
