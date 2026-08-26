# Roadmap

## Phase 0 — Foundation

Repo scaffold, CI pipeline, architecture doc, and a running skeleton:
mock backend, gateway, Streamlit playground, docker-compose stack.
Chaos test against the mock backend: 5/5 requests succeeded while a
replica was killed and the circuit breaker tripped at the configured
threshold.

## Phase 1 — Real model serving

vLLM running end to end — gateway → router → vLLM → GPU — confirmed via
`backend: "vllm"` in the response (see `docs/BENCHMARKS.md` for the
latency number). Runs on an RTX 4070 Laptop GPU (8GB) via WSL2.

Two upstream bugs were diagnosed and fixed rather than left as
undocumented friction, both covered in `docs/LOCAL_GPU_SETUP.md`:

- `RuntimeError: UVA is not available` — a confirmed upstream vLLM/WSL2
  bug ([vllm-project/vllm#47387](https://github.com/vllm-project/vllm/issues/47387)),
  worked around with `VLLM_WSL2_ENABLE_PIN_MEMORY=1` and `--enforce-eager`.
- `Could not find nvcc` — WSL2 ships the NVIDIA driver but not the CUDA
  toolkit; the toolkit is installed separately.

`llama.cpp` (CPU, no GPU required) is wired up with the same backend
adapter pattern as vLLM — see `docs/LOCAL_CPU_SETUP.md`. The HPC path
(`docs/HPC_SETUP.md`) is a secondary option: access there is partial and
doesn't allow installing software.

**Open work:** re-measuring latency without `--enforce-eager` once the
upstream fix ships, adding streaming responses, and running the chaos
test against two real backend replicas instead of one.

## Phase 2 — Observability

Prometheus metrics from the gateway: a latency histogram
(P50/P95/P99 via `histogram_quantile`), request counters by
status/replica/backend, token throughput counters, and live per-replica
gauges (in-flight requests, circuit breaker state, consecutive failures)
via a custom collector (`gateway/app/main.py: RouterStateCollector`)
that reads `router.status()` at scrape time.

A Grafana dashboard (`observability/grafana-dashboards/infermesh-overview.json`)
auto-provisions on `docker compose up` via `observability/grafana-provisioning/`.
Covered by `tests/test_metrics.py`, which hits `/v1/completions` and
asserts the metrics actually move.

**Known gap:** the `status="error"` request path can't identify which
replica failed (see `observability/grafana-dashboards/README.md`).

## Phase 3 — Kubernetes

Deployed to a minikube cluster: 2 gateway pods, the consumer, and
Kafka/Zookeeper all reach `Running`, and a request through `kubectl
port-forward` returns a real response from an in-cluster pod.

The reliability claim from Phase 0 holds against real Kubernetes pod
churn: killing a live gateway pod (`chaos/kill_k8s_pod.sh`) left
**40/40 concurrent requests returning HTTP 200**, with the replacement
pod reaching Ready in ~8s. Full results in `chaos/RESULTS.md` Test 2;
`docs/SLO.md` has the corresponding numbers.

Helm chart additions: `imagePullPolicy` set explicitly (unset defaults
to `Always` for the `latest` tag, which breaks locally-built minikube
images with `ImagePullBackOff`), Kafka/Zookeeper deployments (previously
docker-compose-only), a Service for the consumer, a zero-downtime
rolling-update strategy, and a basic label-based canary deployment
(`gateway.canary.enabled`, off by default — traffic split by pod count,
not exact percentage; a weighted/progressive rollout would need Argo
Rollouts or Flagger).

The consumer's Kafka connection had no retry logic and crashed on a
startup-ordering race (`CrashLoopBackOff` on first deploy, since Kafka
wasn't always ready before the consumer started). Fixed with
`wait_for_kafka_and_start()` — retry with backoff — tested in
`tests/test_kafka_consumer_retry.py`.

The PodDisruptionBudget's enforcement is confirmed with a real
Kubernetes eviction error, not a passing config check: `kubectl drain
--dry-run=server` reported both gateway pods as evictable (a real
limitation of dry-run mode — it doesn't mutate state between checks, so
it can't reveal sequential PDB enforcement across multiple pods in one
run). A real, non-dry-run drain gave the correct result: the first pod
evicted normally, the second was rejected with *"Cannot evict pod as it
would violate the pod's disruption budget."* Full account in
`chaos/RESULTS.md` Test 3.

**Known gaps:** no Prometheus/Grafana in-cluster (stays in
docker-compose); HPA scales on CPU, not the custom
`infermesh_replica_in_flight` metric; Kafka/Zookeeper are single-replica
with no persistent storage (demo-scoped).

## Phase 4 — Independent event consumers

A second Kafka consumer, `kafka/consumer/archiver.py`, with its own
consumer group (`infermesh-event-archiver`), writes every event to a
durable JSONL log — proof the event pipeline supports genuine pub-sub
decoupling, not just a single working consumer. The Kafka
retry-with-backoff logic from Phase 3 was extracted into a shared
`kafka/consumer/retry.py` used by both consumers.

**Verified**: sending 10 real completion requests produced exactly 10
events counted independently by both consumer groups
(`infermesh_events_consumed_total` on `:9100`,
`infermesh_events_archived_total` on `:9101`) — the actual pub-sub
proof, measured rather than inferred.

**Known gap:** not yet added to the Kubernetes Helm chart (Phase 3) —
docker-compose only.

## Phase 5 — Load testing

A concurrency sweep against the mock backend (1/10/50/100 simulated
users, `loadtest/locustfile.py`) shows zero failures and linear
throughput scaling (0.84 → 68.74 req/s). Applying Little's Law to the
numbers shows the router's 20-request backpressure cap was never
triggered at this load — Locust's realistic pacing keeps actual
concurrent in-flight requests well below the simulated user count.

A second Locust user class, `BurstUser` (no wait between requests),
targets the backpressure path directly. An earlier version of that test
masked every 503 as a generic success, hiding the exact behavior it was
meant to measure; fixed by firing a separately-named Locust event on
503 so it appears as its own row. Real result: **45.05% of requests
correctly received a 503** under sustained no-wait load from 30 users
(11,646 of 25,852) — the backpressure path is exercised, not just
defined in code. The latency percentiles from that specific run are
reported with a caveat: Locust itself flagged client-side CPU
saturation during the burst, so the pass/reject counts are trusted, the
specific latency numbers from that run are not.

**Known gap:** this is mock-backend only. The same sweep against real
vLLM or llama.cpp, and the quantization/continuous-batching optimization
comparisons from the original plan, are still open.

## Phase 6 — Eval harness, CI, control room polish

`eval/harness.py`: pure, network-free scoring logic
(`check_must_contain`) separated from the async HTTP runner. A new eval
case, `pagedattention_explanation`, is tied directly to a real bug from
Phase 1 — a live Qwen2.5-3B-Instruct-AWQ run described PagedAttention as
access control instead of KV-cache memory management — so that
regression is now caught automatically. Unit-tested
(`tests/test_eval_harness.py`) and confirmed against a real gateway:
correctly fails the deterministic checks against the mock backend's
canned text, correctly passes the rubric-only cases (which have no
deterministic check and await human/judge review).

Wired into CI (`.github/workflows/ci.yml`, `eval-harness-smoke-test`
job) as a smoke test, not a quality gate — it proves the harness runs
end to end, not that the mock backend passes an eval it was never meant
to pass. The CI matrix was also missing the `archiver` Docker build
target (added in Phase 4); fixed alongside it.

`docs/SLO.md` is filled in with real measured numbers for every SLO
that had them. One gap surfaced while doing that: the P50
time-to-first-token SLO can't be measured as stated, because the
gateway doesn't implement streaming responses — noted directly rather
than substituted with a different number that isn't the same
measurement.

`chaos/RESULTS.md` has a summary table at the top for quick scanning,
full detail preserved below it.

The Streamlit control room has an A/B Compare tab: the same prompt sent
to two gateway URLs side by side (e.g. mock vs. real vLLM), sharing a
`call_completion()` helper with the Playground tab. Unit-tested
(`tests/test_streamlit_helpers.py`) and confirmed to start cleanly.

**Not implemented:** LLM-as-judge scoring for the `rubric` field on each
eval case. Grading a model's output with the same model is a real
methodological weakness, not something to build around quietly — an
independent judge model is the correct next step here.

**Open work:** a demo GIF for the README, showing the Streamlit control
room in action.

## Known limitations, project-wide

- No token streaming in the gateway.
- HPA scales on CPU, not the custom in-flight-requests metric.
- Kafka/Zookeeper run single-replica with no persistent storage —
  fine for a demo, not for production.
- LLM-as-judge scoring is not implemented; the eval harness's
  deterministic checks are.
- The load-test and benchmark numbers on record are mock-backend only;
  the same tests against a real backend would give the throughput
  numbers that matter most for a hiring decision.
- No Prometheus/Grafana inside the Kubernetes cluster — that stack
  stays in docker-compose.
