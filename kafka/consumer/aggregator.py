"""
Consumes `inference.events` and re-exposes rolling aggregates as Prometheus
metrics on :9100/metrics. Kept as a separate process/pod from the gateway
deliberately (see docs/DESIGN.md#event-pipeline): the metrics path can fall
behind or restart without touching request serving.

This is one of (now) two independent consumers of the same topic — see
kafka/consumer/archiver.py for the other, and docs/ROADMAP.md Phase 4 for
why having two matters (proving the event stream is genuinely decoupled,
not just "one consumer happens to work").
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from aiokafka import AIOKafkaConsumer
from prometheus_client import Counter, Histogram, start_http_server

from kafka.consumer.retry import wait_for_kafka_and_start

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("infermesh.kafka_consumer")

EVENTS_CONSUMED = Counter(
    "infermesh_events_consumed_total", "Events consumed from Kafka", ["replica_id", "status"]
)
COMPLETION_LATENCY = Histogram(
    "infermesh_backend_latency_ms", "Per-replica backend latency (ms)", ["replica_id", "backend"],
    buckets=(25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)


async def run() -> None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    metrics_port = int(os.environ.get("CONSUMER_METRICS_PORT", "9100"))

    start_http_server(metrics_port)
    logger.info("Consumer metrics exposed on :%d/metrics", metrics_port)

    consumer = AIOKafkaConsumer(
        "inference.events",
        bootstrap_servers=bootstrap,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        group_id="infermesh-metrics-aggregator",
    )
    await wait_for_kafka_and_start(consumer)
    logger.info("Consumer connected to Kafka at %s", bootstrap)
    try:
        async for msg in consumer:
            event = msg.value
            replica_id = event.get("replica_id", "unknown")
            status = event.get("status", "unknown")
            EVENTS_CONSUMED.labels(replica_id=replica_id, status=status).inc()
            if "latency_ms" in event:
                COMPLETION_LATENCY.labels(
                    replica_id=replica_id, backend=event.get("backend", "unknown")
                ).observe(event["latency_ms"])
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(run())
