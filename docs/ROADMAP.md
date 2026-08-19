# Roadmap

- [x] **Phase 0** — Repo scaffold, CI, architecture doc, running skeleton
      (mock backend, gateway, Streamlit playground, docker-compose).
- [x] **Phase 1 (partial)** — vLLM backend adapter + launch/stop scripts for
      running it against a local NVIDIA GPU (auto-detects VRAM, picks a
      model that fits). See `docs/LOCAL_GPU_SETUP.md`. HPC path kept as a
      secondary option in `docs/HPC_SETUP.md` (access there is partial and
      doesn't allow installing software). Still open: streaming responses,
      and re-running the Phase 0 chaos test against two real replicas
      instead of one.
- [ ] **Phase 2** — Observability: Prometheus metrics from the gateway
      (latency histograms, request counters, queue depth), Grafana dashboard.
- [ ] **Phase 3** — Kubernetes: Helm chart, 2+ replicas, HPA on custom metric,
      liveness/readiness probes, PodDisruptionBudget, canary rollout.
- [ ] **Phase 4** — Kafka event pipeline: gateway emits per-request events,
      consumer aggregates into rolling metrics store.
- [ ] **Phase 5** — Load testing (Locust) + optimization loop, written up in
      `docs/BENCHMARKS.md` with before/after numbers per change.
- [ ] **Phase 6** — Eval harness wired into CI, chaos scripts + observed
      behavior writeup, SLO doc, polished Streamlit control room with
      A/B compare and chaos button, demo GIF in README.

Each phase should land as its own PR with a clean diff — that PR history is
itself part of the portfolio.
