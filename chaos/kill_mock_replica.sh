#!/usr/bin/env bash
# Chaos test #1: kill a mock replica via the gateway's admin endpoint and
# confirm the router routes around it (circuit breaker opens), then
# revive it and confirm it rejoins rotation.
#
# Usage:
#   ./chaos/kill_mock_replica.sh mock-0 http://localhost:8000
#
# What to check while this runs (write the observed result into
# chaos/RESULTS.md): does /status show circuit_open=true for the killed
# replica within one failed request? Does traffic keep flowing to the
# other replica with zero dropped requests? Does reviving it bring it
# back into rotation without a restart?

set -euo pipefail

REPLICA_ID="${1:?usage: kill_mock_replica.sh <replica_id> [gateway_url]}"
GATEWAY_URL="${2:-http://localhost:8000}"

echo "== Before =="
curl -s "$GATEWAY_URL/status" | python3 -m json.tool

echo "== Killing $REPLICA_ID =="
curl -s -X POST "$GATEWAY_URL/admin/chaos/$REPLICA_ID/kill" | python3 -m json.tool

echo "== Sending 5 requests, expect them to succeed via the other replica =="
for i in $(seq 1 5); do
  curl -s -X POST "$GATEWAY_URL/v1/completions" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "chaos test request", "max_tokens": 16}' \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'served by: {d[\"replica_id\"]}')"
done

echo "== After (note circuit_open for $REPLICA_ID) =="
curl -s "$GATEWAY_URL/status" | python3 -m json.tool

echo "== Reviving $REPLICA_ID =="
curl -s -X POST "$GATEWAY_URL/admin/chaos/$REPLICA_ID/revive" | python3 -m json.tool
