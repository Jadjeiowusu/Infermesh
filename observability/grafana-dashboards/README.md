# Grafana Dashboards

Built out in Phase 2 (see `docs/ROADMAP.md`). Planned panels:

- Request latency P50/P95/P99 (from `infermesh_request_latency_seconds`)
- Throughput (requests/sec, tokens/sec) by replica
- Circuit breaker state per replica
- Kafka consumer lag / events processed per second
- Backend latency distribution (from `infermesh_backend_latency_ms`)

Dashboard JSON will be checked in here and auto-provisioned via the
`grafana` service volume mount in `docker/docker-compose.yml`.
