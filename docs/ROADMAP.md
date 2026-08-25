# Roadmap

- [x] **Phase 0** — Repo scaffold, CI, architecture doc, running skeleton
      (mock backend, gateway, Streamlit playground, docker-compose).
- [x] **Phase 1** — Real vLLM backend verified working end to end: gateway
      → router → vLLM → GPU, confirmed via `backend: "vllm"` in the
      response (see `docs/BENCHMARKS.md` for the first real latency
      number). Ran on an RTX 4070 Laptop GPU (8GB) via WSL2, after
      diagnosing and working around two real WSL2/vLLM bugs — documented
      in `docs/LOCAL_GPU_SETUP.md` rather than left as tribal knowledge:
      - `RuntimeError: UVA is not available` — confirmed upstream bug
        ([vllm-project/vllm#47387](https://github.com/vllm-project/vllm/issues/47387)),
        worked around with `VLLM_WSL2_ENABLE_PIN_MEMORY=1` + `--enforce-eager`
      - `Could not find nvcc` — WSL2 only provides the NVIDIA driver, not
        the CUDA toolkit; installed separately
      llama.cpp (CPU, no GPU needed) also wired up for the Ubuntu laptop —
      see `docs/LOCAL_CPU_SETUP.md` — not yet run for real, but same
      adapter pattern as vLLM. HPC path kept as a secondary option in
      `docs/HPC_SETUP.md` (access there is partial and doesn't allow
      installing software). Still open: re-measuring without
      `--enforce-eager` once the upstream bug allows it, streaming
      responses, and re-running the Phase 0 chaos test against two real
      replicas instead of one (works for either backend once a second
      instance exists).
- [x] **Phase 2** — Prometheus metrics from the gateway: latency
      histogram (P50/P95/P99 via `histogram_quantile`), request counters
      by status/replica/backend, token throughput counters, and
      live per-replica gauges (in-flight requests, circuit breaker state,
      consecutive failures) via a custom collector
      (`gateway/app/main.py: RouterStateCollector`) that reads
      `router.status()` at scrape time — no Gauge-syncing code needed in
      the request path. Grafana dashboard (`observability/grafana-
      dashboards/infermesh-overview.json`) auto-provisions on `docker
      compose up` via `observability/grafana-provisioning/`. Covered by
      real tests (`tests/test_metrics.py`) that hit `/v1/completions` and
      assert the metrics actually move, not just that they're declared.
      Known gap: the `status="error"` path can't yet identify which
      replica failed (see `observability/grafana-dashboards/README.md`).
- [ ] **Phase 3 (built, not yet verified live)** — Helm chart extended:
      fixed a real gap (`imagePullPolicy` was unset, which would have
      caused `ImagePullBackOff` on locally-built minikube images since
      `latest` defaults to `Always`), added Kafka/Zookeeper deployments
      (previously docker-compose-only, so the chart had nothing for the
      gateway to actually talk to), a Service for the consumer, an
      explicit zero-downtime rolling-update strategy, and a basic
      label-based canary deployment (`gateway.canary.enabled`, off by
      default — traffic split by pod count, not exact percentage; a real
      weighted/progressive rollout needs Argo Rollouts or Flagger, out of
      scope here). Full walkthrough in `k8s/DEPLOY.md`, including running
      the real chaos test (`chaos/kill_k8s_pod.sh`, built in Phase 0,
      unused until now) against an actual pod instead of the mock
      backend's in-process health flag. Not marked done because none of
      it has run against a live cluster yet — that's the next step.
      Known gaps, tracked rather than hidden: no Prometheus/Grafana
      in-cluster (stays in `docker compose` from Phase 2), HPA still
      scales on CPU not the custom `infermesh_replica_in_flight` metric
      exposed since Phase 2, Kafka/Zookeeper are single-replica/no
      persistent storage (demo-scoped only).
- [ ] **Phase 4** — Independent Kafka consumers. The event pipeline itself
      (gateway emits per-request events, one consumer aggregates them into
      metrics) already exists since Phase 0 and is now visualized in
      Phase 2's dashboard — what's still open is proving a *second*,
      independent consumer group can subscribe to the same
      `inference.events` topic without touching the metrics consumer
      (e.g. an eval-pipeline consumer, per the original design intent in
      `docs/DESIGN.md`), which is the actual test of "decoupled event
      stream" rather than just "one consumer works."
- [ ] **Phase 5** — Load testing (Locust) + optimization loop, written up in
      `docs/BENCHMARKS.md` with before/after numbers per change.
- [ ] **Phase 6** — Eval harness wired into CI, chaos scripts + observed
      behavior writeup, SLO doc, polished Streamlit control room with
      A/B compare and chaos button, demo GIF in README.

Each phase should land as its own PR with a clean diff — that PR history is
itself part of the portfolio.
