from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram, make_asgi_app
from pydantic import BaseModel

from gateway.app.router import NoHealthyReplicaError, Router
from kafka.producer.events import EventEmitter
from serving.backend import build_backends_from_env

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("infermesh.gateway")

REQUEST_LATENCY = Histogram(
    "infermesh_request_latency_seconds", "End-to-end gateway latency", ["status"]
)
REQUEST_COUNT = Counter(
    "infermesh_requests_total", "Total completion requests", ["status", "replica_id"]
)

router: Router | None = None
emitter: EventEmitter | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global router, emitter
    backends = build_backends_from_env()
    router = Router(backends=backends)
    emitter = EventEmitter()
    await emitter.start()
    logger.info("InferMesh gateway started with %d replica(s)", len(backends))
    yield
    await emitter.stop()


app = FastAPI(title="InferMesh Gateway", lifespan=lifespan)
app.mount("/metrics", make_asgi_app())


class CompletionRequest(BaseModel):
    prompt: str
    max_tokens: int = 256


class CompletionResponse(BaseModel):
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    backend: str
    replica_id: str


@app.post("/v1/completions", response_model=CompletionResponse)
async def completions(req: CompletionRequest):
    assert router is not None and emitter is not None
    start = time.perf_counter()
    try:
        result = await router.complete(req.prompt, req.max_tokens)
    except NoHealthyReplicaError:
        REQUEST_LATENCY.labels(status="rejected").observe(time.perf_counter() - start)
        raise HTTPException(status_code=503, detail="no healthy replica available")
    except Exception as exc:  # noqa: BLE001
        REQUEST_LATENCY.labels(status="error").observe(time.perf_counter() - start)
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}") from exc

    REQUEST_LATENCY.labels(status="ok").observe(time.perf_counter() - start)
    REQUEST_COUNT.labels(status="ok", replica_id=result.replica_id).inc()

    await emitter.emit(
        {
            "replica_id": result.replica_id,
            "backend": result.backend,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "latency_ms": result.latency_ms,
            "status": "ok",
        }
    )

    return CompletionResponse(
        text=result.text,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        latency_ms=result.latency_ms,
        backend=result.backend,
        replica_id=result.replica_id,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/status")
async def status():
    assert router is not None
    return {"replicas": router.status()}


@app.post("/admin/chaos/{replica_id}/{action}")
async def chaos_toggle(replica_id: str, action: str):
    """
    Dev/demo-only endpoint: flips a mock replica's health so the Streamlit
    control room's chaos button has something real to trigger. Only works
    against MockBackend instances (real vLLM/llama.cpp replicas are killed
    via the scripts in chaos/, which act on the actual process/pod).
    """
    assert router is not None
    if action not in ("kill", "revive"):
        raise HTTPException(status_code=400, detail="action must be 'kill' or 'revive'")

    for replica in router.replicas:
        if replica.backend.replica_id == replica_id:
            if not hasattr(replica.backend, "set_healthy"):
                raise HTTPException(
                    status_code=400,
                    detail="chaos toggle only supported on the mock backend",
                )
            replica.backend.set_healthy(action == "revive")  # type: ignore[attr-defined]
            return {"replica_id": replica_id, "action": action, "ok": True}

    raise HTTPException(status_code=404, detail=f"unknown replica: {replica_id}")
