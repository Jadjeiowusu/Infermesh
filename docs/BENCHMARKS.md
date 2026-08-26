# Benchmarks

Format for every entry: baseline number → change → new number → eval-score
delta (does the change trade away quality?). Numbers come from
`loadtest/locustfile.py` runs; eval scores come from `eval/prompts/`.

## Phase 1 first real number (vLLM, single manual request, not yet load-tested)

First real (non-mock) measurement, from the gateway's own `latency_ms`
field on a single request — not a proper benchmark run (that's Phase 5,
via `loadtest/locustfile.py` sweeping concurrency), but a real data point
worth recording rather than losing.

| Metric | Value | Conditions |
|---|---|---|
| Single-request round trip (gateway → vLLM → gateway) | 2804ms | `Qwen/Qwen2.5-3B-Instruct-AWQ`, RTX 4070 Laptop (8GB), WSL2, `--enforce-eager`, 41 completion tokens, 1 client |
| Mock backend for comparison | ~130-180ms | same gateway/router code path, mock backend |

**`--enforce-eager` is doing a lot of that latency**, not the model or
GPU. It disables CUDA graph capture and `torch.compile`, both major vLLM
speed optimizations — it was added only to work around a WSL2-specific
bug (`vllm-project/vllm#47387`, see `docs/LOCAL_GPU_SETUP.md`), not
because eager mode was the goal. Once that upstream bug is fixed or a
workaround without `--enforce-eager` is found, re-measuring without it is
the natural next entry — expect a substantial drop, and that delta itself
becomes a legitimate "cost of a workaround" benchmark row.

**Eval note, not a benchmark number but adjacent:** the same request
("Explain PagedAttention in one sentence") returned a factually wrong
answer — the 3B AWQ model described PagedAttention as an access-control
mechanism, not the actual KV-cache memory management technique. Not a
pipeline bug; it's a real illustration of why the eval harness
(`eval/prompts/basic_suite.yaml`, Phase 6) needs to exist rather than
trusting that a running server means correct answers.

## Phase 0 baseline (mock backend, informal, not load-tested)

Sanity numbers from manual testing, not a real benchmark run — recorded
here as a placeholder so the format is established before Phase 5's actual
load-test entries.

| Metric | Value | Conditions |
|---|---|---|
| Single-request round trip | ~130–180ms | mock backend, 1 client, local |
| Gateway overhead over raw backend call | not yet isolated | TODO Phase 5 |

## Phase 5: mock backend concurrency sweep (real, `loadtest/locustfile.py`)

2 gateway replicas, mock backend, `docker compose` on WSL2. 30s per run,
`--spawn-rate` scaled with `--users` (1/1, 10/5, 50/10, 100/20).

| Simulated users | POST /v1/completions RPS | Median | P95 | P99 | Failures |
|---|---|---|---|---|---|
| 1 | 0.84 | 150ms | 190ms | 210ms | 0/25 |
| 10 | 6.10 | 160ms | 190ms | 190ms | 0/217 |
| 50 | 34.49 | 160ms | 190ms | 200ms | 0/1025 |
| 100 | 68.74 | 160ms | 190ms | 190ms | 0/2050 |

**Throughput scales linearly with simulated users across this range, and
latency stays flat** (median pinned at ~150-160ms, P95 at ~190ms,
regardless of load) — the mock backend's own simulated latency
(`base_latency_ms=120` + up to 60ms jitter, from `serving/backend.py`)
dominates end-to-end time at every concurrency level tested. Zero request
failures throughout, at every level.

**The honest finding, not just the headline number:** the router's
backpressure cap (`max_in_flight_per_replica=10` × 2 replicas = 20
concurrent requests before a 503) was **never actually triggered**, even
at 100 simulated users. Why: Locust's default `wait_time` (0.2-1.0s
between requests per simulated user, set in `loadtest/locustfile.py`)
means each "user" spends most of its time idle between requests, not
holding a request open. By Little's Law (concurrency ≈ throughput ×
average service time), actual concurrent in-flight requests at 100
simulated users was only ~10.5 — comfortably under the 20-request cap:

| Simulated users | Measured RPS | Actual concurrent in-flight (Little's Law) |
|---|---|---|
| 1 | 0.84 | ~0.1 |
| 10 | 6.10 | ~1.0 |
| 50 | 34.49 | ~5.2 |
| 100 | 68.74 | ~10.5 |

So this run proves the gateway scales cleanly and linearly under this
particular load shape — a real, useful result — but does **not** prove
anything about the backpressure/503 path, which remains genuinely
untested. Confirming that needs either a much higher simulated-user count
or a Locust load shape with little-to-no `wait_time` between requests
(a burst/hammer pattern), so actual concurrency crosses 20. Worth doing
as a explicit follow-up rather than assuming linear scaling continues
past the point this data actually covers.

## Phase 5 follow-up: burst test, backpressure path (real, proven)

Added a second Locust user class, `BurstUser` (`wait_time = constant(0)`
— no pause between requests), specifically to push actual concurrency
above the 20-request cap. 30 simulated users, 20s run, `docker compose`
on WSL2, mock backend.

**A real bug in the test itself, caught before trusting its first
result:** the original locustfile marked every 503 as `resp.success()`
(correct — a 503 under overload is the router behaving as designed, not
a load-test failure) but did nothing else to distinguish it from a 200.
The first burst run showed **0 failures** and a suspicious bimodal
latency split (median 11ms, P90 jumping to 170ms) — the tell that many
requests were being fast-rejected while the "0 failures" number silently
hid it. Fixed by firing a separately-named Locust event
(`/v1/completions [503 backpressure]`) whenever a 503 occurs, so it shows
up as its own row in the stats table instead of being folded into the
200 count.

**Real result after the fix:**

| Outcome | Count | % of total |
|---|---|---|
| 200 (succeeded) | 14,206 | 54.95% |
| 503 (backpressure, correctly rejected) | 11,646 | 45.05% |
| **Total attempted** | **25,852** | |

Combined attempted throughput at steady state: ~1,305 req/s (717 req/s
succeeding, 588 req/s correctly rejected) from just 30 concurrent
no-wait clients — confirming the router's overload protection is real
and gets exercised heavily under this load shape, not merely defined in
code and never hit.

**Honest caveat on the latency numbers specifically (not the counts):**
Locust itself printed `CPU usage above 90%!` during this run, warning
that response-time measurements may be unreliable once the load
generator itself is CPU-saturated — plausible here, since 30 users
firing continuously with zero wait time on the same WSL2 machine running
the whole stack is a demanding client-side load, not just a server-side
one. The pass/reject **counts** are a real per-request server outcome
and stand regardless; the specific latency percentiles from this run
(e.g. successful requests showing an implausibly low median of ~11ms,
when the mock backend simulates ~120-180ms) are not trusted as precise
and are not reported as a clean before/after latency number here. A
properly isolated version of this test — separate machine for the load
generator, or Locust's own distributed-load mode — is the honest next
step before quoting exact burst-mode latencies.
