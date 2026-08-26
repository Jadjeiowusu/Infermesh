# Running InferMesh Against a Real Model, Locally

Phase 0 ran entirely on the mock backend. This is Phase 1: pointing the
gateway at a real vLLM server running on your own machine's GPU.

This is the primary path — not the HPC. School HPC access is partial,
VPN-gated, and doesn't allow installing software, which makes it fragile
to build a repeatable demo on. Your own GPU (NVIDIA, 8GB VRAM) is fully
under your control and needs nothing installed anywhere you don't already
have permission.

## Windows users: WSL2 required

vLLM does not support native Windows — `pip install vllm` will fail or
behave unpredictably outside a Linux environment (long-path/build errors
are typically the first symptom, not the real cause). Run this entire doc
inside WSL2 (`wsl --install -d Ubuntu-24.04` from an admin PowerShell),
not directly in PowerShell/cmd. WSL2 uses your existing Windows NVIDIA
driver via GPU passthrough — no separate driver install needed inside
WSL2, just verify with `nvidia-smi` once you're in the Ubuntu terminal.
The bash scripts below (`launch_vllm_local.sh` etc.) also require a real
shell, which is another reason this needs to run inside WSL2 rather than
PowerShell.

**Work inside WSL2's native filesystem (`~/`), not `/mnt/c/...`.** The
Windows-mounted path is 3-5x slower for file-heavy work (model downloads,
pip installs) and can still trip path-length issues since it's NTFS
underneath. Clone/build everything under your Linux home directory.

## Two WSL2-specific bugs you will hit, and how they're handled

Both are already worked around automatically by `launch_vllm_local.sh`
(WSL2-detection logic added after hitting these for real) — documented
here so the reasoning isn't a black box if something changes upstream.

**1. `RuntimeError: UVA is not available`** — vLLM's newer v1 engine
(`GPUModelRunnerV2`) tries to use CUDA's Unified Virtual Addressing, which
WSL2's GPU passthrough doesn't expose the same way native Linux does.
Confirmed upstream bug:
[vllm-project/vllm#47387](https://github.com/vllm-project/vllm/issues/47387)
(same GPU class — RTX 4050/4070 laptop — same traceback). Workaround:
`VLLM_WSL2_ENABLE_PIN_MEMORY=1` env var plus `--enforce-eager`. The
launch script sets both automatically when it detects WSL2
(`grep -qi microsoft /proc/version`).

**2. `Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't
exist`** — happens *after* the model loads, when `flashinfer` tries to
JIT-compile its sampling kernel. The NVIDIA driver (what `nvidia-smi`
needs) is not the same thing as the CUDA *toolkit* (what `nvcc` needs) —
WSL2 gives you GPU passthrough via the driver alone, but the compiler
toolchain still needs a real install:

```bash
wget https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update
sudo apt-get -y install cuda-toolkit   # NOT plain 'cuda' — that package tries
                                        # to install a conflicting Linux display
                                        # driver; WSL2 uses the Windows driver
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
```

Add those two `export` lines to `~/.bashrc` for persistence — but check
first whether anything else in `.bashrc` (a conda/venv auto-activation
hook, for instance) resets `PATH` on every new shell, since that can
silently undo them.

**Status: verified working end to end** on an RTX 4070 Laptop GPU (8GB)
with both workarounds — `Qwen/Qwen2.5-3B-Instruct-AWQ` served real
completions through the gateway, confirmed via `backend: "vllm"` in the
response. See `docs/BENCHMARKS.md` for the first real numbers.

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

Use a **separate** venv from vLLM's — they have very different dependency
trees, don't mix them (see `docs/DESIGN.md`).

```bash
sudo apt install -y python3-venv   # if this venv's bin/ ends up missing pip
python3 -m venv .venv-gateway
~/Infermesh/.venv-gateway/bin/pip install -r gateway/requirements.txt
MODEL_BACKEND=vllm REPLICA_ENDPOINTS=http://localhost:8000 VLLM_MODEL=Qwen/Qwen2.5-3B-Instruct-AWQ PYTHONPATH=. \
  ~/Infermesh/.venv-gateway/bin/python -m uvicorn gateway.app.main:app --port 9000
```

Two things worth knowing if this venv misbehaves:
- **`python3 -m venv` can silently create a venv with no `pip`** if the
  `python3-venv` apt package isn't installed — `ls .venv-gateway/bin/`
  should show `pip`/`pip3` alongside `python`; if it doesn't, `apt install
  python3-venv` and recreate the venv.
- **Calling binaries by absolute path (`.venv-gateway/bin/pip`,
  `.venv-gateway/bin/python`)** rather than relying on `source
  .venv-gateway/bin/activate` sidesteps any shell hook (e.g. a
  conda/venv auto-activation script in `.bashrc` for another project)
  that might silently override `PATH` after activation.

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

The original design assumed an 8B-class model as the default. At 8GB of
VRAM on a laptop GPU also driving the display, even the AWQ-quantized 8B
model is too tight once KV-cache overhead is accounted for — 3B is the
realistic fit. Model size is a real infrastructure constraint, not a
detail: picking the right size for the available hardware is itself an
engineering decision, and `docs/BENCHMARKS.md` records both the choice
and the reasoning alongside the numbers.

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
