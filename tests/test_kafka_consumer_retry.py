"""
Tests the retry-with-backoff behavior added to kafka/consumer/aggregator.py
after discovering (via a real Phase 3 Kubernetes deployment) that the
consumer crashed outright if Kafka wasn't ready yet at pod startup.
"""

from unittest.mock import AsyncMock

import pytest

from kafka.consumer.aggregator import wait_for_kafka_and_start


@pytest.mark.asyncio
async def test_succeeds_immediately_when_kafka_is_ready():
    consumer = AsyncMock()
    consumer.start = AsyncMock(return_value=None)

    await wait_for_kafka_and_start(consumer, max_attempts=5, base_delay=0.01, max_delay=0.01)

    consumer.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_retries_then_succeeds_once_kafka_becomes_ready():
    consumer = AsyncMock()
    # Fails twice (Kafka not ready), succeeds on the third attempt
    consumer.start = AsyncMock(side_effect=[ConnectionError("not ready"),
                                             ConnectionError("not ready"),
                                             None])

    await wait_for_kafka_and_start(consumer, max_attempts=5, base_delay=0.01, max_delay=0.01)

    assert consumer.start.await_count == 3


@pytest.mark.asyncio
async def test_gives_up_and_raises_after_max_attempts():
    consumer = AsyncMock()
    consumer.start = AsyncMock(side_effect=ConnectionError("kafka never comes up"))

    with pytest.raises(ConnectionError):
        await wait_for_kafka_and_start(consumer, max_attempts=3, base_delay=0.01, max_delay=0.01)

    assert consumer.start.await_count == 3
