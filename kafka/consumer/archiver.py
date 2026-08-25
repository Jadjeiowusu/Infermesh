"""
Second, independent consumer of `inference.events` — proves the event
pipeline is genuinely decoupled (per docs/DESIGN.md's original intent),
not just "one consumer happens to work". Runs as its own Kafka consumer
group (`infermesh-event-archiver`), so Kafka delivers it a full copy of
every event, completely independently of kafka/consumer/aggregator.py's
consumer group — killing, restarting, or falling behind on one has zero
effect on the other.

Writes each event as one JSON line to a durable log file — the simplest
possible "second consumer with a different job" (an audit/archive log,
not metrics aggregation). This also happens to be useful groundwork for
Phase 6's eval harness, which will want a durable record of real
request/response pairs to build eval cases from, though that wiring
isn't built yet — this only proves the event stream can support a second
consumer, it doesn't do eval-harness-specific work itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from aiokafka import AIOKafkaConsumer
from prometheus_client import Counter, start_http_server

from kafka.consumer.retry import wait_for_kafka_and_start

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("infermesh.kafka_archiver")

EVENTS_ARCHIVED = Counter(
    "infermesh_events_archived_total", "Events written to the archive log", ["status"]
)


def append_event(path: Path, event: dict) -> None:
    """Appends one event as a JSON line. Separated out so it's directly
    unit-testable without needing a real Kafka connection."""
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


async def run() -> None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    metrics_port = int(os.environ.get("ARCHIVER_METRICS_PORT", "9101"))
    archive_path = Path(os.environ.get("ARCHIVE_LOG_PATH", "./archived_events.jsonl"))
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    start_http_server(metrics_port)
    logger.info("Archiver metrics exposed on :%d/metrics", metrics_port)
    logger.info("Archiving events to %s", archive_path)

    consumer = AIOKafkaConsumer(
        "inference.events",
        bootstrap_servers=bootstrap,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        # Different group_id from aggregator.py's "infermesh-metrics-aggregator"
        # is the whole point — this is what makes Kafka treat it as an
        # independent subscriber entitled to its own full copy of the
        # topic, rather than competing with the metrics consumer for the
        # same partition assignments.
        group_id="infermesh-event-archiver",
    )
    await wait_for_kafka_and_start(consumer)
    logger.info("Archiver connected to Kafka at %s", bootstrap)
    try:
        async for msg in consumer:
            event = msg.value
            append_event(archive_path, event)
            EVENTS_ARCHIVED.labels(status=event.get("status", "unknown")).inc()
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(run())
