"""
Router: owns replica selection, retries, and circuit breaking. Kept
separate from the FastAPI app (main.py) so it can be unit tested without
spinning up HTTP at all — see tests/test_router.py.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from serving.backend import CompletionResult, ModelBackend


@dataclass
class ReplicaState:
    backend: ModelBackend
    in_flight: int = 0
    consecutive_failures: int = 0
    open_until: float = 0.0  # circuit breaker: unhealthy until this timestamp

    def is_open(self) -> bool:
        return time.time() < self.open_until


class NoHealthyReplicaError(Exception):
    pass


class Router:
    """
    Least-outstanding-requests load balancing with per-replica circuit
    breaking. A replica that fails `failure_threshold` times consecutively
    is skipped for `cooldown_seconds`, then given another chance.
    """

    def __init__(
        self,
        backends: list[ModelBackend],
        max_in_flight_per_replica: int = 10,
        failure_threshold: int = 3,
        cooldown_seconds: float = 15.0,
    ):
        self.replicas: list[ReplicaState] = [ReplicaState(backend=b) for b in backends]
        self.max_in_flight_per_replica = max_in_flight_per_replica
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

    def _eligible_replicas(self) -> list[ReplicaState]:
        return [
            r for r in self.replicas
            if not r.is_open() and r.in_flight < self.max_in_flight_per_replica
        ]

    def pick_replica(self, exclude: set[str] | None = None) -> ReplicaState:
        exclude = exclude or set()
        candidates = [
            r for r in self._eligible_replicas()
            if r.backend.replica_id not in exclude
        ]
        if not candidates:
            raise NoHealthyReplicaError("no healthy replica with capacity")
        return min(candidates, key=lambda r: r.in_flight)

    async def complete(self, prompt: str, max_tokens: int = 256,
                        max_retries: int = 1) -> CompletionResult:
        tried: set[str] = set()
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                replica = self.pick_replica(exclude=tried)
            except NoHealthyReplicaError:
                if last_error:
                    raise last_error
                raise

            tried.add(replica.backend.replica_id)
            replica.in_flight += 1
            try:
                result = await replica.backend.complete(prompt, max_tokens)
                replica.consecutive_failures = 0
                return result
            except Exception as exc:  # noqa: BLE001 - any backend failure trips the breaker
                last_error = exc
                replica.consecutive_failures += 1
                if replica.consecutive_failures >= self.failure_threshold:
                    replica.open_until = time.time() + self.cooldown_seconds
                if attempt == max_retries:
                    raise
            finally:
                replica.in_flight -= 1

        # unreachable, but keeps type checkers happy
        raise last_error  # type: ignore[misc]

    def status(self) -> list[dict]:
        return [
            {
                "replica_id": r.backend.replica_id,
                "in_flight": r.in_flight,
                "circuit_open": r.is_open(),
                "consecutive_failures": r.consecutive_failures,
            }
            for r in self.replicas
        ]
