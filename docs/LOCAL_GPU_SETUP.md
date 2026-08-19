# Running InferMesh Against a Real Model, Locally

Phase 0 ran entirely on the mock backend. This is Phase 1: pointing the
gateway at a real vLLM server running on your own machine's GPU.

This is the primary path — not the HPC. School HPC access is partial,
VPN-gated, and doesn't allow installing software, which makes it fragile
to build a repeatable demo on. Your own GPU (NVIDIA, 8GB VRAM) is fully
under your control and needs nothing installed anywhere you don't already
have permission.

## 1. Install vLLM

```bash
pip install vllm
```

## 2. Launch it

```bash
./scripts/launch_vllm_local.sh
```

No arguments needed — the script detects your VRAM via `nvidia-smi` and
picks a model sized to fit. At 8GB, that's `Qwen/Qwen2.5-3B-Instruct-AWQ`
(quantized to INT4). Logs go to `./logs/`; wait for `Uvicorn running` in
the log before continuing.

If it fails with an out-of-memory error (common on a laptop GPU that's
also driving your display), retry with lower utilization:

```bash
./scripts/launch_vllm_local.sh Qwen/Qwen2.5-3B-Instruct-AWQ 8000 0.55
```

Stop it with `./scripts/stop_vllm_local.sh`.

## 3. Point the gateway at it

```bash
MODEL_BACKEND=vllm \
REPLICA_ENDPOINTS=http://localhost:8000 \
VLLM_MODEL=Qwen/Qwen2.5-3B-Instruct-AWQ \
PYTHONPATH=. python -m uvicorn gateway.app.main:app --port 9000
```

(Gateway on 9000, vLLM on 8000 — both local, so they need different ports.)

## 4. Sanity check

```bash
curl -X POST http://localhost:9000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain PagedAttention in one sentence.", "max_tokens": 64}'
```

`backend` in the response should say `"vllm"`, and `latency_ms` will
reflect real inference time — this is the first real number to record in
`docs/BENCHMARKS.md`, replacing the mock backend's simulated ~150ms.

## Why 3B instead of the 8B model from the original design

The Phase 0 design assumed an 8B-class model as the default. At 8GB of
VRAM on a laptop GPU also driving the display, even the AWQ-quantized 8B
model is too tight once KV-cache overhead is accounted for — 3B is the
realistic fit. This is worth stating plainly in an interview rather than
hidden: model size is a real infrastructure constraint, not a detail, and
picking the right size for the hardware you actually have is itself an
engineering decision. `docs/BENCHMARKS.md` should record both the model
choice and the reasoning, not just the numbers.

## Constraints of this setup

- **Single replica.** Same caveat as the HPC path would have had — the
  chaos test that passed cleanly against two mock replicas (see
  `chaos/RESULTS.md`) has nothing to fail over to with one real GPU. Note
  this explicitly rather than re-running the chaos script and getting a
  misleading "it failed" result — it's expected to fail with only one
  replica, that's not a regression.
- **Shared with the OS.** Running vLLM ties up most of your GPU; expect
  the rest of your system to slow down while it's running, and close other
  GPU-heavy applications (browser with hardware acceleration, other model
  servers) before a demo.
- **No process supervision**, same as the HPC path would have had — this
  is still the gap Phase 3's Kubernetes deployment closes.

## HPC as a secondary option

If HPC access opens up later (a module system, Apptainer/Singularity, or
permission to install), `docs/HPC_SETUP.md` and
`scripts/launch_vllm_hpc.sh` are still there — but don't block Phase 1 on
it. The local path is what to build and demo against now.
