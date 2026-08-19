# Benchmarks

Format for every entry: baseline number → change → new number → eval-score
delta (does the change trade away quality?). Numbers come from
`loadtest/locustfile.py` runs; eval scores come from `eval/prompts/`.

## Phase 0 baseline (mock backend, informal, not load-tested)

Sanity numbers from manual testing, not a real benchmark run — recorded
here as a placeholder so the format is established before Phase 5's actual
load-test entries.

| Metric | Value | Conditions |
|---|---|---|
| Single-request round trip | ~130–180ms | mock backend, 1 client, local |
| Gateway overhead over raw backend call | not yet isolated | TODO Phase 5 |

## Phase 5 (planned entries)

- [ ] Baseline: 1 replica, mock backend, 1/10/50/100 concurrent users
      (throughput, P50/P95/P99 latency)
- [ ] Real model baseline: 1 replica, llama.cpp or vLLM, same concurrency
      sweep
- [ ] Optimization: continuous batching on vs off (vLLM) — throughput gain,
      eval-score delta
- [ ] Optimization: INT8/AWQ quantization vs FP16 — throughput gain,
      latency change, eval-score delta (this is the entry that matters most
      to a hiring manager: does faster mean worse, and by how much)
- [ ] Optimization: prefix/KV-cache reuse on repeated-prefix prompts —
      throughput gain specifically on that workload shape
- [ ] Scaling: 1 replica vs 2 vs 4 — throughput and tail latency under
      fixed load, plus whether HPA reacted in time

Nothing below this line is real yet — fill in as Phase 5 work lands, and
do not backfill fabricated numbers.
