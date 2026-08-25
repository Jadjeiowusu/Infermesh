"""
Shared retry-with-backoff logic for connecting to Kafka, used by every
consumer under kafka/consumer/. Extracted here after aggregator.py needed
it (see docs/ROADMAP.md Phase 3) and archiver.py needed the identical
fix — duplicating it a second time would have been the wrong call.
"""

from __future__ import annotations

import asyncio
import logging

from aiokafka import AIOKafkaConsumer

logger = logging.getLogger("infermesh.kafka_consumer")


async def wait_for_kafka_and_start(consumer: AIOKafkaConsumer, max_attempts: int = 30,
                                    base_delay: float = 2.0, max_delay: float = 30.0) -> None:
    """
    Retries consumer.start() with backoff instead of letting a Kafka-not-ready
    error crash the whole process. Discovered as a real gap during Phase 3
    k8s testing: the gateway's EventEmitter is deliberately fail-soft against
    Kafka being briefly unavailable (see docs/DESIGN.md), but a consumer's
    connection had no equivalent protection — it crashed outright if Kafka
    wasn't ready yet (a real, observed startup-ordering race in Kubernetes,
    where a pod can start before Kafka/Zookeeper are ready), relying on
    Kubernetes' CrashLoopBackOff to eventually retry it. That "worked" but is
    noisy and slower than necessary — this waits in-process instead.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            await consumer.start()
            return
        except Exception as exc:  # noqa: BLE001 - any connection failure should retry, not crash
            if attempt == max_attempts:
                logger.error("Giving up connecting to Kafka after %d attempts", max_attempts)
                raise
            delay = min(base_delay * attempt, max_delay)
            logger.warning(
                "Kafka not ready yet (attempt %d/%d): %s — retrying in %.1fs",
                attempt, max_attempts, exc, delay,
            )
            await asyncio.sleep(delay)
