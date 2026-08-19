# Running InferMesh Against a Real Model on the HPC (secondary option)

> **This is not the primary path.** School HPC access here is partial,
> VPN-gated, and software can't be installed on it — `pip install vllm`
> below will likely fail as written. The primary Phase 1 path is
> [`docs/LOCAL_GPU_SETUP.md`](LOCAL_GPU_SETUP.md), running against your own
> GPU. Revisit this doc only if HPC access changes (a module system,
> Apptainer/Singularity, or install permission becomes available).

Phase 0 ran entirely on the mock backend. This doc covers pointing the
gateway at a real vLLM server running on the HPC, reached over VPN — kept
for later, not blocking Phase 1.

## 1. Launch vLLM on the HPC node

SSH into the HPC node over VPN as usual, then from the repo root:

```bash
pip install vllm  # one-time, if not already installed
./scripts/launch_vllm_hpc.sh meta-llama/Llama-3.1-8B-Instruct 8000 0.90
```

This backgrounds the server with `nohup` (matching how jobs are normally
run here — no scheduler in front of it) and writes logs to
`~/infermesh-logs/`. Wait for `Uvicorn running on http://0.0.0.0:8000` in
the log before continuing — first-run model download/compilation can take
a few minutes.

Find the node's IP (needed in step 2):

```bash
hostname -I
```

Stop it later with `./scripts/stop_vllm_hpc.sh`.

## 2. Point the gateway at it

On your laptop (with VPN connected), run the gateway with:

```bash
MODEL_BACKEND=vllm \
REPLICA_ENDPOINTS=http://<hpc-node-ip>:8000 \
VLLM_MODEL=meta-llama/Llama-3.1-8B-Instruct \
PYTHONPATH=. python -m uvicorn gateway.app.main:app --port 8000
```

`REPLICA_ENDPOINTS` takes a comma-separated list — if you get a second GPU
or launch a second vLLM instance on another port, add it there and the
router's load balancing and circuit breaking apply exactly as they did
against the mock backend, no code changes.

## 3. Sanity check

```bash
curl -X POST http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain PagedAttention in one sentence.", "max_tokens": 64}'
```

`backend` in the response should now say `"vllm"` instead of `"mock"`, and
`latency_ms` will reflect real inference time instead of the mock's
simulated ~150ms.

## Known constraints of this setup

- **Single point of failure until a second replica exists.** With one
  vLLM instance, the router's retry/circuit-breaker logic has nothing to
  fail over to — `chaos/RESULTS.md`'s Phase 0 test (5/5 requests survived
  a killed replica) won't hold here until there's a second `REPLICA_ENDPOINTS`
  entry. Worth re-running that chaos test once a second GPU/instance is
  available, and recording the real-backend result alongside the mock one.
- **VPN dependency.** If the VPN drops mid-session, the gateway's health
  checks against the vLLM endpoint will start failing and the circuit
  breaker will (correctly) open — that's expected behavior, not a bug, but
  worth knowing before a demo.
- **No process supervision.** `nohup` doesn't restart vLLM if it crashes
  (e.g. OOM). This is exactly the gap Phase 3's Kubernetes deployment
  (with liveness probes and automatic restarts) closes — worth calling out
  explicitly in an interview as the reason the k8s phase exists, not just
  a checkbox.
