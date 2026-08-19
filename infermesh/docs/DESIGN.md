# Design Notes

## Why a gateway in front of the model servers at all?

vLLM and llama.cpp both expose an OpenAI-compatible API on their own. The
gateway exists to own the concerns that a single model server shouldn't:
routing across replicas, retrying a failed request against a different
replica, shedding load before a replica falls over, and emitting a uniform
event stream regardless of which backend served the request. This mirrors
why you'd put a gateway in front of any fleet of stateful backends — the
model server should not need to know it's one of several.

## Backends

The gateway talks to model replicas through one interface
(`serving/backend.py: ModelBackend`), with three implementations:

- **mock** — deterministic, near-instant fake completions. Default for
  local dev and CI. Lets every other layer (routing, Kafka, k8s, chaos,
  load testing) be built and tested without a GPU.
- **llama_cpp** — wraps a local `llama-server` (or `llama-cpp-python`)
  process. Realistic latency profile on CPU, good for laptop-scale demos.
- **vllm** — wraps a vLLM OpenAI-compatible server. This is the "real"
  production path: continuous batching, PagedAttention KV-cache, and where
  quantization (AWQ/INT8) tradeoffs get measured in `docs/BENCHMARKS.md`.

Swapping backends is a single env var (`MODEL_BACKEND`) — no gateway code
changes. This separation is deliberate: it's what lets Phases 2-6
(observability, k8s, Kafka, load testing, chaos) get built and proven out
immediately, in parallel with real-model work, instead of blocking on GPU
access.

## Routing and reliability

- **Load balancing**: least-outstanding-requests across healthy replicas,
  not naive round-robin — round-robin sends new work to a replica that's
  still draining a slow request.
- **Retries**: a failed request is retried once against a different replica
  (never the one that just failed), with a hard budget so retries can't
  cascade into a self-inflicted overload.
- **Circuit breaking**: a replica that fails N requests in a window is
  marked unhealthy and skipped by the router until it passes a health check
  again — this is what the chaos tests in `chaos/` are exercising.
- **Backpressure**: the gateway caps in-flight requests per replica and
  returns 429 rather than queuing unboundedly once the cap is hit.

## Event pipeline

Every completed (or failed) request emits one event to the
`inference.events` Kafka topic: replica id, latency, token counts, success/
failure, backend type. The consumer (`kafka/consumer/`) aggregates these
into the metrics the Grafana dashboards read. Kafka is used here — rather
than the gateway writing metrics directly — so that the metrics path can go
down or fall behind without affecting request serving, and so that other
consumers (e.g. an eval pipeline, or an analytics job) can subscribe to the
same event stream independently.

## What "optimization" means in `docs/BENCHMARKS.md`

Every optimization entry states: the baseline number, the change, the new
number, and — critically — whether output quality moved (via the eval
suite). A 2x throughput gain that also drops eval accuracy is a tradeoff,
not a free win, and the writeup treats it that way.
