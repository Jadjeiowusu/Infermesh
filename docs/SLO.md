# Service Level Objectives

Declared upfront so Phase 5/6 load testing and chaos testing have a
concrete target to measure against, rather than "seems fine."

## Availability

| SLO | Target | Status |
|---|---|---|
| Successful response rate under normal load (not deliberately overloaded) | ≥ 99.5% over any 5-min window | **met** — 100% success (0 failures / 4,110 requests) across the full Phase 5 concurrency sweep (1/10/50/100 simulated users, mock backend, `docs/BENCHMARKS.md`) |
| Correct rejection rate under deliberate overload | N/A — expected, not a violation | Under intentional burst load exceeding the router's 20-request capacity (30 no-wait concurrent clients), 45.05% of requests correctly received a 503 (`docs/BENCHMARKS.md` Phase 5 follow-up). This is the system protecting itself as designed, not a violation of the row above — the 99.5% target is scoped to traffic within capacity, and a clean 503 under genuine overload is a different, also-met SLO ("reject visibly rather than degrade silently or crash"), not a failure of this one. |
| Zero visible request failures during single-replica loss | 0 dropped requests | **met** in both the Phase 0 mock chaos test (5/5 requests succeeded, `chaos/RESULTS.md`) and the Phase 3 real k8s chaos test (40/40 requests returned HTTP 200 during an actual pod deletion, `chaos/RESULTS.md` Test 2) |

## Latency

| SLO | Target | Status |
|---|---|---|
| P50 time-to-first-token | < 300ms at 10 concurrent users | **Not literally measurable** — the gateway doesn't implement token streaming; every response returns as one complete block, so there's no separate "time to first token" distinct from full completion time. The closest proxy: P50 end-to-end latency at 10 concurrent users was 160ms (mock backend, `docs/BENCHMARKS.md`), comfortably under 300ms — but this is a full-response number standing in for a token-level one, not the same measurement. |
| P99 end-to-end latency | < 2s at 50 concurrent users | **Met for mock backend**: P99 was 200ms at 50 concurrent users (`docs/BENCHMARKS.md`). **Unverified for a real backend** (vLLM/llama.cpp) at any concurrency — the only real-backend number on record is a single request at 2804ms (Phase 1, `--enforce-eager` workaround overhead included), already over this threshold, but that's one request with no concurrency and a known-costly workaround active, not a real measurement against this SLO. Running the Phase 5 concurrency sweep against real vLLM instead of mock is the natural next step to actually answer this. |

## Recovery

| SLO | Target | Status |
|---|---|---|
| Circuit breaker opens within N consecutive failures | ≤ 3 failed requests | **met** — confirmed in Phase 0 chaos test |
| Replacement pod Ready after a k8s pod kill | < 30s | **met** — ~8s observed (`chaos/RESULTS.md` Test 2) |
| PodDisruptionBudget blocks a voluntary eviction that would violate `minAvailable` | Real Kubernetes eviction error, not just a config that looks right | **met** — confirmed with an actual `kubectl drain`, not a dry-run (which gave a misleading "would succeed" result for a reason worth knowing — see `chaos/RESULTS.md` Test 3): the real eviction API rejected the second gateway pod with *"Cannot evict pod as it would violate the pod's disruption budget"* |

Every row without a real number gets one once the corresponding work
lands.
