# Service Level Objectives

Declared upfront so Phase 5/6 load testing and chaos testing have a
concrete target to measure against, rather than "seems fine."

## Availability

| SLO | Target | Status |
|---|---|---|
| Successful response rate (excl. client errors) | ≥ 99.5% over any 5-min window | not yet measured |
| Zero visible request failures during single-replica loss | 0 dropped requests | **met** in both the Phase 0 mock chaos test (5/5 requests succeeded, `chaos/RESULTS.md`) and the Phase 3 real k8s chaos test (40/40 requests returned HTTP 200 during an actual pod deletion, `chaos/RESULTS.md` Test 2) |

## Latency (target backend: TBD in Phase 1 — vLLM or llama.cpp)

| SLO | Target | Status |
|---|---|---|
| P50 time-to-first-token | < 300ms at 10 concurrent users | not yet measured |
| P99 end-to-end latency | < 2s at 50 concurrent users | not yet measured |

## Recovery

| SLO | Target | Status |
|---|---|---|
| Circuit breaker opens within N consecutive failures | ≤ 3 failed requests | **met** — confirmed in Phase 0 chaos test |
| Replacement pod Ready after a k8s pod kill | < 30s | **met** — ~8s observed (`chaos/RESULTS.md` Test 2) |

Every "not yet measured" row gets a real number, not a guess, once the
corresponding phase lands — this file is meant to be embarrassing if left
stale, which is the point.
