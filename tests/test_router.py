import pytest

from gateway.app.router import NoHealthyReplicaError, Router
from serving.backend import MockBackend


@pytest.mark.asyncio
async def test_routes_to_least_loaded_replica():
    backends = [MockBackend("r0", base_latency_ms=1, jitter_ms=0),
                MockBackend("r1", base_latency_ms=1, jitter_ms=0)]
    router = Router(backends=backends)
    router.replicas[0].in_flight = 5
    picked = router.pick_replica()
    assert picked.backend.replica_id == "r1"


@pytest.mark.asyncio
async def test_successful_completion_returns_result():
    backends = [MockBackend("r0", base_latency_ms=1, jitter_ms=0)]
    router = Router(backends=backends)
    result = await router.complete("hello world")
    assert result.replica_id == "r0"
    assert result.text


@pytest.mark.asyncio
async def test_retries_against_a_different_replica_on_failure():
    failing = MockBackend("r0", base_latency_ms=1, jitter_ms=0, failure_rate=1.0)
    healthy = MockBackend("r1", base_latency_ms=1, jitter_ms=0)
    router = Router(backends=[failing, healthy])
    result = await router.complete("hello world", max_retries=1)
    assert result.replica_id == "r1"


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold_failures():
    failing = MockBackend("r0", base_latency_ms=1, jitter_ms=0, failure_rate=1.0)
    router = Router(backends=[failing], failure_threshold=2, cooldown_seconds=60)

    for _ in range(2):
        with pytest.raises(Exception):
            await router.complete("hello", max_retries=0)

    assert router.replicas[0].is_open()
    with pytest.raises(NoHealthyReplicaError):
        router.pick_replica()


@pytest.mark.asyncio
async def test_no_healthy_replica_raises():
    down = MockBackend("r0", base_latency_ms=1, jitter_ms=0, failure_rate=1.0)
    router = Router(backends=[down], failure_threshold=1, cooldown_seconds=60)
    with pytest.raises(Exception):
        await router.complete("hello", max_retries=0)
    with pytest.raises(NoHealthyReplicaError):
        router.pick_replica()
