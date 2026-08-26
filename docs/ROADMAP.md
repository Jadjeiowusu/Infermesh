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
      backoff), tested in `tests/test_kafka_consumer_retry.py`. This fix
      took two attempts to actually land: the first rebuild was assumed
      to include it but didn't — the fix had been packaged and presented
      but never actually unzipped/committed into the working repo before
      the rebuild ran, so the old code got rebuilt unchanged. A real
      crash traceback (`kubectl logs --previous`) caught this directly —
      `line 43, in run: await consumer.start()` was unmistakably the old
      code, not the new retry wrapper — rather than the mistake going
      unnoticed. Re-applied, committed, pushed, and rebuilt properly the
      second time; confirmed via a clean zero-restart pod on redeploy
      (different ReplicaSet hash, confirming a genuinely new image).
      The PDB question is also resolved: `kubectl drain --dry-run=server`
      gave a misleading "would succeed" result for both gateway pods (a
      real limitation — dry-run evictions don't mutate state, so
      sequential PDB enforcement across multiple pods in the same run
      can't be observed that way). A real (non-dry-run) drain gave the
      true answer: the first gateway pod evicted normally, the second was
      correctly and repeatedly rejected with Kubernetes' actual eviction
      error — *"Cannot evict pod as it would violate the pod's disruption
      budget."* Full account in `chaos/RESULTS.md` Test 3.
      Known gaps, tracked rather than hidden: no Prometheus/Grafana
      in-cluster (stays in `docker compose` from Phase 2), HPA still
      scales on CPU not the custom `infermesh_replica_in_flight` metric
      exposed since Phase 2, Kafka/Zookeeper are single-replica/no
      persistent storage (demo-scoped only, and confirmed disruptive to
      the consumer on recreation, per the retry-fix story above).
- [x] **Phase 4** — Second, independent Kafka consumer:
      `kafka/consumer/archiver.py`, its own consumer group
      (`infermesh-event-archiver`), writes every event to a durable JSONL
      log — proof the topic supports genuine pub-sub decoupling, not just
      "one consumer works." Refactored the Kafka retry-with-backoff fix
      (`wait_for_kafka_and_start`, from the Phase 3 consumer bug) into a
      shared `kafka/consumer/retry.py` rather than duplicating it a second
      time. Unit-tested (`tests/test_archiver.py`,
      `tests/test_kafka_consumer_retry.py` now imports the shared
      module). Wired into `docker-compose.yml` (own Prometheus port 9101,
      a named Docker volume so the archive log survives container
      restarts) and into `observability/prometheus/prometheus.yml`'s
      scrape config.
      **Verified live**: sent 10 real completion requests through the
      gateway and confirmed both consumer groups independently counted
      exactly 10 events each (`infermesh_events_consumed_total` on
      `:9100` and `infermesh_events_archived_total` on `:9101`) — the
      actual pub-sub proof, not inferred.
      Hit and resolved a real environment footgun along the way, worth
      remembering: `eval $(minikube docker-env)` (used in Phase 3) sets
      `DOCKER_HOST` etc. for the current shell session and doesn't
      un-set itself — a terminal that had run it earlier silently pointed
      `docker compose up` at minikube's *internal* Docker daemon instead
      of the regular one. Everything looked fine (`docker compose ps`
      showed all containers healthy) but nothing was reachable on
      `localhost`, since the "published" ports lived inside minikube's
      own network. Diagnosed via `env | grep -i docker` /
      `echo $MINIKUBE_ACTIVE_DOCKERD`, fixed with `unset DOCKER_TLS_VERIFY
      DOCKER_HOST DOCKER_CERT_PATH MINIKUBE_ACTIVE_DOCKERD`. Worth
      checking `env | grep -i docker` first any time `docker compose ps`
      and `curl localhost:<port>` disagree about whether something is
      actually running.
      Known gap: not yet added to the Kubernetes Helm chart (Phase 3) —
      docker-compose only for now, noted rather than silently skipped.
      Archive-file content inspection (`cat archived_events.jsonl`) was
      not completed — a separate, still-unexplained terminal issue kept
      reporting the container as not running even while its metrics
      endpoint responded correctly. Not chased further since the core
      pub-sub claim was already conclusively proven by the matched
      counters; worth revisiting if it recurs.
- [x] **Phase 5** — Load testing against the mock backend, real results in
      `docs/BENCHMARKS.md`: a concurrency sweep (1/10/50/100 simulated
      users, `InferMeshUser`) showed zero failures and linear throughput
      scaling (0.84 → 68.74 req/s), but also revealed — via Little's Law
      applied to the actual numbers — that the router's 20-request
      backpressure cap was never once triggered, because Locust's
      realistic pacing (`wait_time` between requests) keeps actual
      concurrent in-flight requests far below simulated user count.
      Added a second user class (`BurstUser`, no wait between requests)
      specifically to close that gap, and in doing so caught a real bug
      in the test itself: the original locustfile marked every 503 as a
      Locust "success" (correct, since a 503 under overload isn't a load
      test failure) but did nothing to distinguish it from a 200 in the
      stats — so the very case being tested for was invisible in its own
      report. Fixed by firing a separately-named Locust event on 503, so
      it shows as its own row. Real result after the fix: **45.05% of
      requests correctly received a 503** under sustained no-wait load
      from 30 users (11,646 of 25,852) — the backpressure path is real
      and gets exercised, not just defined in code. Reported the latency
      numbers from that run with an honest caveat rather than as clean
      data: Locust itself warned of client-side CPU saturation during the
      burst test, so the pass/reject counts are trusted, the specific
      latency percentiles from that run are not.
      Known gap: this is mock-backend only — the same sweep against real
      vLLM (Phase 1) or llama.cpp (still not run for real) would give the
      actual GPU/CPU throughput numbers a hiring manager would care about
      most; the quantization/continuous-batching optimization entries
      from the original Phase 5 plan are also still open.
- [ ] **Phase 6** — Eval harness wired into CI, chaos scripts + observed
      behavior writeup, SLO doc, polished Streamlit control room with
      A/B compare and chaos button, demo GIF in README.

Each phase should land as its own PR with a clean diff — that PR history is
itself part of the portfolio.
