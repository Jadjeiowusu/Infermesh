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
- [x] **Phase 3** — Deployed to a real minikube cluster and verified live,
      not just built: 2 gateway pods + consumer + Kafka/Zookeeper all
      reached `Running`, a request through `kubectl port-forward` returned
      a real response from an in-cluster pod, and the actual chaos test
      (`chaos/kill_k8s_pod.sh`, built in Phase 0, unused until now) killed
      a live gateway pod while **40/40 concurrent requests kept returning
      HTTP 200** — a stronger, more directly measured result than Phase
      0's mock-backend version. Replacement pod reached Ready in ~8s. Full
      results in `chaos/RESULTS.md` Test 2; `docs/SLO.md` updated with the
      real numbers.
      Helm chart work: fixed a real gap (`imagePullPolicy` was unset,
      which would have caused `ImagePullBackOff` on locally-built minikube
      images since `latest` defaults to `Always`), added Kafka/Zookeeper
      deployments (previously docker-compose-only — the chart had nothing
      for the gateway to talk to), a Service for the consumer, an explicit
      zero-downtime rolling-update strategy, and a basic label-based
      canary deployment (`gateway.canary.enabled`, off by default —
      traffic split by pod count, not exact percentage; a real
      weighted/progressive rollout needs Argo Rollouts or Flagger, out of
      scope here).
      A second real gap was found *during* this live test, not just
      predicted: the consumer pod crash-looped 4 times on first deploy
      (`CrashLoopBackOff`) because its Kafka connection had no retry
      logic, unlike the gateway's deliberately fail-soft `EventEmitter`
      from Phase 0. Fixed with `wait_for_kafka_and_start()` (retry with
      backoff), tested in `tests/test_kafka_consumer_retry.py` — this fix
      has not yet been rebuilt/redeployed to the live cluster, so the
      *fix* itself is unverified live even though the *problem* was.
      Known gaps, tracked rather than hidden: no Prometheus/Grafana
      in-cluster (stays in `docker compose` from Phase 2), HPA still
      scales on CPU not the custom `infermesh_replica_in_flight` metric
      exposed since Phase 2, Kafka/Zookeeper are single-replica/no
      persistent storage (demo-scoped only), and the PDB's actual
      enforcement (`kubectl drain --dry-run=server`) hasn't been checked
      yet — `kill_k8s_pod.sh` uses direct pod deletion, which PDBs don't
      govern.
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
