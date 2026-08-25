# Grafana Dashboards

`infermesh-overview.json` is auto-provisioned on `docker compose up` — no
manual import needed. Grafana at `http://localhost:3000` (default
login: `admin` / `admin`, set via `GF_SECURITY_ADMIN_PASSWORD` in
`docker/docker-compose.yml`) picks it up via
`observability/grafana-provisioning/`, which wires up the Prometheus
datasource and points Grafana at this folder.

## Panels

- **Request rate by status** — `ok` / `error` / `rejected`, from
  `infermesh_requests_total`
- **Gateway latency P50/P95/P99** — from
  `infermesh_request_latency_seconds` (a histogram, so percentiles come
  from `histogram_quantile` over the bucket data, not a raw average)
- **Token throughput** — prompt and completion tokens/sec, from
  `infermesh_prompt_tokens_total` / `infermesh_completion_tokens_total`
- **In-flight requests per replica** — `infermesh_replica_in_flight`,
  read live from the router's own state via a custom Prometheus collector
  (`gateway/app/main.py: RouterStateCollector`) rather than a Gauge kept
  in sync by hand
- **Circuit breaker state** — `infermesh_replica_circuit_open`, a
  state-timeline panel so a replica going unhealthy is visually obvious
  during a chaos test, not just a number in a table
- **Backend inference latency (P95)** — from the Kafka consumer's
  `infermesh_backend_latency_ms`, labeled by backend (`mock` / `vllm` /
  `llama_cpp`) — this is the panel that will make a real CPU-vs-GPU
  comparison visible once both backends have been run
- **Kafka events consumed** — `infermesh_events_consumed_total`, confirms
  the event pipeline (gateway → Kafka → consumer) is actually flowing,
  not just that the gateway itself is healthy

## Known gap

The `status="error"` request-count metric currently labels the failing
replica as `"unknown"` — `router.py`'s `complete()` re-raises the
backend's raw exception without attaching which replica it came from, so
the gateway can't tell which replica actually failed on that path (this
is noted inline in `gateway/app/main.py`). Fine for now since `error`
should be rare with the circuit breaker in place, but worth fixing before
leaning on per-replica error-rate panels for anything load-bearing.
