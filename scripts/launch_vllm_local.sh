#!/usr/bin/env bash
# Launch vLLM locally against your own NVIDIA GPU. Detects available VRAM
# and picks a model/quantization that should fit, so you don't have to
# know the exact number upfront. Override anytime with explicit args.
#
# Usage:
#   ./scripts/launch_vllm_local.sh [model] [port] [gpu_memory_utilization]
#
# Examples:
#   ./scripts/launch_vllm_local.sh                                  # auto-pick model
#   ./scripts/launch_vllm_local.sh Qwen/Qwen2.5-3B-Instruct-AWQ 8000 0.70

set -euo pipefail

PORT="${2:-8000}"
GPU_MEM_UTIL="${3:-0.70}"
LOG_DIR="${LOG_DIR:-./logs}"
mkdir -p "$LOG_DIR"

if ! command -v nvidia-smi &> /dev/null; then
    echo "nvidia-smi not found — is the NVIDIA driver installed?" >&2
    exit 1
fi

VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
VRAM_GB=$((VRAM_MB / 1024))
echo "Detected GPU VRAM: ${VRAM_GB}GB"

# On a laptop, the GPU is also driving the display and (on Intel Core
# Ultra chips) may be sharing thermal/power budget with an integrated GPU
# doing the actual display output — either way, leave more headroom than
# you would on a headless desktop or server card. Default util above
# reflects that (0.70, not vLLM's more aggressive typical default of 0.90).
USE_QUANTIZATION=true

if [[ -n "${1:-}" ]]; then
    MODEL="$1"
    echo "Using explicitly requested model: $MODEL"
elif [[ "$VRAM_GB" -ge 20 ]]; then
    MODEL="meta-llama/Llama-3.1-8B-Instruct"
    USE_QUANTIZATION=false
    echo "Selected: Llama-3.1-8B-Instruct (FP16) — fits comfortably at ${VRAM_GB}GB"
elif [[ "$VRAM_GB" -ge 10 ]]; then
    MODEL="hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4"
    echo "Selected: Llama-3.1-8B-Instruct AWQ INT4 — quantized to fit ${VRAM_GB}GB"
elif [[ "$VRAM_GB" -ge 7 ]]; then
    MODEL="Qwen/Qwen2.5-3B-Instruct-AWQ"
    echo "Selected: Qwen2.5-3B-Instruct AWQ — sized for an 8GB laptop GPU"
    echo "This is your tier (8GB) — 8B-class models are too tight here even quantized"
    echo "once KV-cache and the OS's own display usage are accounted for."
else
    echo "Only ${VRAM_GB}GB VRAM detected — vLLM will likely struggle even with a small"
    echo "quantized model. Consider the llama.cpp backend instead (CPU-friendly, see"
    echo "serving/backend.py: LlamaCppBackend), or set MODEL_BACKEND=mock for now."
    exit 1
fi

LOG_FILE="$LOG_DIR/vllm-$(date +%Y%m%d-%H%M%S).log"
echo "Launching vLLM on port $PORT (gpu-memory-utilization=$GPU_MEM_UTIL), logging to $LOG_FILE ..."

VLLM_ARGS=(
    --model "$MODEL"
    --host 0.0.0.0
    --port "$PORT"
    --gpu-memory-utilization "$GPU_MEM_UTIL"
    --max-model-len 4096
)
if [[ "$USE_QUANTIZATION" == "true" ]]; then
    VLLM_ARGS+=(--quantization awq)
fi

nohup python -m vllm.entrypoints.openai.api_server "${VLLM_ARGS[@]}" \
    > "$LOG_FILE" 2>&1 &

PID=$!
echo "$PID" > "$LOG_DIR/vllm.pid"
echo "Started with PID $PID."
echo "Tail logs: tail -f $LOG_FILE"
echo ""
echo "If it fails with an out-of-memory error, retry with a lower utilization:"
echo "  ./scripts/launch_vllm_local.sh $MODEL $PORT 0.55"
echo ""
echo "Once you see 'Uvicorn running' in the log, test with:"
echo "  curl http://localhost:$PORT/health"
echo "Then run the gateway (on a different port, since both are local):"
echo "  MODEL_BACKEND=vllm REPLICA_ENDPOINTS=http://localhost:$PORT VLLM_MODEL=$MODEL \\"
echo "    PYTHONPATH=. python -m uvicorn gateway.app.main:app --port 9000"
