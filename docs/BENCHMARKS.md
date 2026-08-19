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
