from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from prometheus_client import REGISTRY, Counter, Histogram, make_asgi_app
from prometheus_client.core import GaugeMetricFamily
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
    "infermesh_requests_total", "Total completion requests", ["status", "replica_id", "backend"]
)
PROMPT_TOKENS = Counter(
    "infermesh_prompt_tokens_total", "Total prompt tokens processed", ["replica_id", "backend"]
)
COMPLETION_TOKENS = Counter(
    "infermesh_completion_tokens_total", "Total completion tokens generated",
    ["replica_id", "backend"],
)

router: Router | None = None
emitter: EventEmitter | None = None


class RouterStateCollector:
    """
    Exposes live router state (in-flight requests, circuit breaker status)
    as Prometheus gauges at scrape time, rather than trying to keep
    separate Gauge objects in sync with router.py's request path. Reading
    router.status() directly here means router.py doesn't need to know
    Prometheus exists at all — see docs/DESIGN.md on keeping the request
    path decoupled from the metrics path.
    """

    def collect(self):
        in_flight = GaugeMetricFamily(
            "infermesh_replica_in_flight",
            "Current in-flight requests per replica",
            labels=["replica_id"],
        )
        circuit_open = GaugeMetricFamily(
            "infermesh_replica_circuit_open",
            "1 if the replica's circuit breaker is currently open (unhealthy), else 0",
            labels=["replica_id"],
        )
        consecutive_failures = GaugeMetricFamily(
            "infermesh_replica_consecutive_failures",
            "Current consecutive failure count per replica",
            labels=["replica_id"],
        )

        if router is not None:
            for replica in router.status():
                rid = replica["replica_id"]
                in_flight.add_metric([rid], replica["in_flight"])
                circuit_open.add_metric([rid], 1 if replica["circuit_open"] else 0)
                consecutive_failures.add_metric([rid], replica["consecutive_failures"])

        yield in_flight
        yield circuit_open
        yield consecutive_failures


REGISTRY.register(RouterStateCollector())


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
        REQUEST_COUNT.labels(status="rejected", replica_id="none", backend="none").inc()
        raise HTTPException(status_code=503, detail="no healthy replica available")
    except Exception as exc:  # noqa: BLE001
        REQUEST_LATENCY.labels(status="error").observe(time.perf_counter() - start)
        # NOTE: router.complete() re-raises the backend's raw exception without
        # attaching which replica failed, so this can't be labeled with a real
        # replica_id/backend today. Known gap: enriching the exception in
        # router.py with the last-tried replica would let this be precise.
        REQUEST_COUNT.labels(status="error", replica_id="unknown", backend="unknown").inc()
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}") from exc

    REQUEST_LATENCY.labels(status="ok").observe(time.perf_counter() - start)
    REQUEST_COUNT.labels(status="ok", replica_id=result.replica_id, backend=result.backend).inc()
    PROMPT_TOKENS.labels(replica_id=result.replica_id, backend=result.backend).inc(
        result.prompt_tokens
    )
    COMPLETION_TOKENS.labels(replica_id=result.replica_id, backend=result.backend).inc(
        result.completion_tokens
    )

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
