"""
ModelBackend: a single interface for completions, implemented by three
adapters (mock / llama_cpp / vllm). The gateway only ever talks to this
interface, so swapping the underlying model server is a config change,
not a code change. See docs/DESIGN.md for the rationale.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CompletionResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    backend: str
    replica_id: str


class ModelBackend(ABC):
    """Interface every model backend adapter must implement."""

    def __init__(self, replica_id: str):
        self.replica_id = replica_id

    @abstractmethod
    async def complete(self, prompt: str, max_tokens: int = 256) -> CompletionResult:
        ...

    @abstractmethod
    async def health(self) -> bool:
        ...


class MockBackend(ModelBackend):
    """
    Deterministic fake backend for local dev, CI, and demoing every layer
    of the platform (routing, Kafka events, k8s, chaos, load testing)
    without needing a GPU. Simulates realistic-ish latency and an
    occasional failure so retry/circuit-breaker logic has something to do.
    """

    def __init__(self, replica_id: str, base_latency_ms: float = 120,
                 jitter_ms: float = 60, failure_rate: float = 0.0):
        super().__init__(replica_id)
        self.base_latency_ms = base_latency_ms
        self.jitter_ms = jitter_ms
        self.failure_rate = failure_rate
        self._healthy = True

    async def complete(self, prompt: str, max_tokens: int = 256) -> CompletionResult:
        start = time.perf_counter()
        if not self._healthy or random.random() < self.failure_rate:
            raise ConnectionError(f"replica {self.replica_id} is unavailable")

        latency_s = (self.base_latency_ms + random.uniform(0, self.jitter_ms)) / 1000
        await asyncio.sleep(latency_s)

        completion_tokens = min(max_tokens, max(8, len(prompt.split())))
        text = f"[mock completion from {self.replica_id}] {prompt[:60]}..."

        return CompletionResult(
            text=text,
            prompt_tokens=len(prompt.split()),
            completion_tokens=completion_tokens,
            latency_ms=(time.perf_counter() - start) * 1000,
            backend="mock",
            replica_id=self.replica_id,
        )

    async def health(self) -> bool:
        return self._healthy

    def set_healthy(self, value: bool) -> None:
        """Used by chaos scripts to simulate a replica going down."""
        self._healthy = value


class LlamaCppBackend(ModelBackend):
    """Adapter for a local llama-server (llama.cpp) OpenAI-compatible endpoint."""

    def __init__(self, replica_id: str, endpoint: str):
        super().__init__(replica_id)
        self.endpoint = endpoint

    async def complete(self, prompt: str, max_tokens: int = 256) -> CompletionResult:
        import httpx

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.endpoint}/v1/completions",
                json={"prompt": prompt, "max_tokens": max_tokens},
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})
        return CompletionResult(
            text=choice["text"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=(time.perf_counter() - start) * 1000,
            backend="llama_cpp",
            replica_id=self.replica_id,
        )

    async def health(self) -> bool:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{self.endpoint}/health")
                return resp.status_code == 200
        except Exception:
            return False


class VLLMBackend(ModelBackend):
    """Adapter for a vLLM OpenAI-compatible server. The production path."""

    def __init__(self, replica_id: str, endpoint: str, model: str):
        super().__init__(replica_id)
        self.endpoint = endpoint
        self.model = model

    async def complete(self, prompt: str, max_tokens: int = 256) -> CompletionResult:
        import httpx

        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.endpoint}/v1/completions",
                json={"model": self.model, "prompt": prompt, "max_tokens": max_tokens},
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})
        return CompletionResult(
            text=choice["text"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=(time.perf_counter() - start) * 1000,
            backend="vllm",
            replica_id=self.replica_id,
        )

    async def health(self) -> bool:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{self.endpoint}/health")
                return resp.status_code == 200
        except Exception:
            return False


def build_backends_from_env() -> list[ModelBackend]:
    """
    Reads MODEL_BACKEND + REPLICA_ENDPOINTS from env and constructs the
    configured backend adapters. This is the single place that decides
    "how many replicas, of what kind" — everything downstream just gets
    a list of ModelBackend.
    """
    backend_type = os.environ.get("MODEL_BACKEND", "mock")
    n_replicas = int(os.environ.get("N_MOCK_REPLICAS", "2"))

    if backend_type == "mock":
        return [MockBackend(replica_id=f"mock-{i}") for i in range(n_replicas)]

    endpoints = os.environ.get("REPLICA_ENDPOINTS", "").split(",")
    endpoints = [e.strip() for e in endpoints if e.strip()]
    if not endpoints:
        raise ValueError(
            "REPLICA_ENDPOINTS must be set (comma-separated) when "
            f"MODEL_BACKEND={backend_type}"
        )

    if backend_type == "llama_cpp":
        return [
            LlamaCppBackend(replica_id=f"llama-{i}", endpoint=ep)
            for i, ep in enumerate(endpoints)
        ]
    if backend_type == "vllm":
        model = os.environ.get("VLLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
        return [
            VLLMBackend(replica_id=f"vllm-{i}", endpoint=ep, model=model)
            for i, ep in enumerate(endpoints)
        ]

    raise ValueError(f"Unknown MODEL_BACKEND: {backend_type}")
