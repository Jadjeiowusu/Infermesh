# InferMesh

A self-hosted, horizontally scalable LLM inference platform: a load-balancing
gateway in front of multiple model replicas, a Kafka-based event/metrics
pipeline, Kubernetes deployment with autoscaling and chaos-tested reliability,
a load/eval harness, and a Streamlit control room for live demoing.

InferMesh is the *serving infrastructure* layer that a system like
[InfraAgent-911](#) would sit on top of — this repo focuses purely on making
LLM inference fast, observable, and resilient at scale, independent of any
single application.

## Why this exists

Most "LLM project" portfolios are a notebook that calls an API. InferMesh is
the opposite: the model is the least interesting part. What's being tested
here is everything *around* the model — routing, backpressure, autoscaling,
graceful degradation, and measurable optimization tradeoffs.

## Architecture

```
                        ┌─────────────────┐
                        │   Streamlit     │
                        │  Control Room   │
                        └────────┬────────┘
                                 │ HTTP
                        ┌────────▼────────┐
                        │     Gateway     │  FastAPI
                        │  (LB, retries,  │
                        │ circuit breaker)│
                        └───┬────────┬────┘
                 ┌──────────┘        └──────────┐
        ┌────────▼────────┐          ┌──────────▼───────┐
        │ Model Replica 1  │          │ Model Replica 2  │
        │ (vLLM / llama.cpp│          │ (vLLM / llama.cpp│
        │  / mock backend) │          │  / mock backend) │
        └────────┬─────────┘          └──────────┬───────┘
                 │      every request emits an event
                 └───────────────┬───────────────┘
                        ┌────────▼────────┐
                        │   Kafka topic:  │
                        │ inference.events│
                        └────────┬────────┘
                        ┌────────▼────────┐
                        │ Metrics Consumer │──▶ Prometheus ──▶ Grafana
                        └─────────────────┘
```

Full diagram source: [`docs/diagrams/architecture.md`](docs/diagrams/architecture.md).
Design rationale and tradeoffs: [`docs/DESIGN.md`](docs/DESIGN.md).

## Repo layout

| Path | Purpose |
|---|---|
| `gateway/` | FastAPI load-balancing gateway: routing, retries, circuit breaking |
| `serving/` | Model backend adapters (vLLM, llama.cpp, mock) behind one interface |
| `kafka/` | Producer (embedded in gateway) and consumer that aggregates metrics |
| `k8s/helm/infermesh/` | Helm chart: deployments, HPA, probes, PDBs |
| `observability/` | Prometheus scrape config + Grafana dashboards |
| `eval/` | Correctness eval suite (exact-match + LLM-as-judge) |
| `loadtest/` | Locust load test scenarios |
| `chaos/` | Scripts that kill replicas / inject latency, with observed-behavior writeups |
| `streamlit_app/` | Control room UI: playground, live metrics, A/B compare, chaos button |
| `docs/BENCHMARKS.md` | Optimization log: baseline → change → measured result |
| `docs/SLO.md` | Declared SLOs and whether the system meets them |

## Quickstart (local dev, no GPU required)

```bash
docker compose -f docker/docker-compose.yml up --build
```

This starts: gateway (2 mock model replicas by default), Kafka + Zookeeper,
the metrics consumer, Prometheus, Grafana, and the Streamlit control room at
`http://localhost:8501`.

To point at a real model instead of the mock backend, set `MODEL_BACKEND=vllm`
and `REPLICA_ENDPOINTS=...`. See [`docs/LOCAL_GPU_SETUP.md`](docs/LOCAL_GPU_SETUP.md)
for running vLLM against your own GPU (the primary path — HPC access here
is partial and doesn't allow installing software, so
[`docs/HPC_SETUP.md`](docs/HPC_SETUP.md) is kept as a secondary option only).

## Status

Build phases tracked in [`docs/ROADMAP.md`](docs/ROADMAP.md). This is Phase 0:
scaffold, CI, and a running skeleton end-to-end.

## License

MIT
