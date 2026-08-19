"""
Best-effort Kafka event emission for the gateway. "Best-effort" is
deliberate: if Kafka is down or slow, request serving must not be affected.
Failures here are logged and swallowed, never raised.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger("infermesh.kafka_producer")

TOPIC = "inference.events"


class EventEmitter:
    def __init__(self, bootstrap_servers: str | None = None):
        self.bootstrap_servers = bootstrap_servers or os.environ.get(
            "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
        )
        self._producer = None

    def _get_producer(self):
        if self._producer is None:
            from aiokafka import AIOKafkaProducer  # imported lazily: optional dep

            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
        return self._producer

    async def start(self) -> None:
        try:
            producer = self._get_producer()
            await producer.start()
        except Exception:  # noqa: BLE001
            logger.warning("Kafka producer failed to start; events will be dropped", exc_info=True)
            self._producer = None

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()

    async def emit(self, event: dict[str, Any]) -> None:
        if self._producer is None:
            return
        event = {**event, "emitted_at": time.time()}
        try:
            await self._producer.send_and_wait(TOPIC, event)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to emit event to Kafka", exc_info=True)
