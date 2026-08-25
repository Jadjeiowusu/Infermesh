"""
Tests kafka/consumer/archiver.py's append_event() directly — the part
that doesn't need a real Kafka connection to verify.
"""

import json
from pathlib import Path

from kafka.consumer.archiver import append_event


def test_append_event_writes_one_json_line(tmp_path: Path):
    log_path = tmp_path / "events.jsonl"
    event = {"replica_id": "mock-0", "status": "ok", "latency_ms": 123.4}

    append_event(log_path, event)

    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == event


def test_append_event_appends_multiple_events_in_order(tmp_path: Path):
    log_path = tmp_path / "events.jsonl"
    events = [
        {"replica_id": "mock-0", "status": "ok"},
        {"replica_id": "mock-1", "status": "error"},
        {"replica_id": "mock-0", "status": "ok"},
    ]

    for event in events:
        append_event(log_path, event)

    lines = log_path.read_text().splitlines()
    assert len(lines) == 3
    assert [json.loads(line) for line in lines] == events


def test_append_event_creates_file_if_missing(tmp_path: Path):
    log_path = tmp_path / "subdir_does_not_exist_yet" / "events.jsonl"
    log_path.parent.mkdir(parents=True)  # append_event itself doesn't mkdir — run() does

    append_event(log_path, {"replica_id": "mock-0", "status": "ok"})

    assert log_path.exists()
