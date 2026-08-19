"""
Load test the gateway's /v1/completions endpoint. Used in Phase 5 to
produce the before/after tables in docs/BENCHMARKS.md.

Run locally:
    locust -f loadtest/locustfile.py --host http://localhost:8000

Headless, for scripted benchmark runs (e.g. 50 concurrent users for 60s):
    locust -f loadtest/locustfile.py --host http://localhost:8000 \
        --users 50 --spawn-rate 10 --run-time 60s --headless \
        --csv loadtest/results/run_50users
"""

from __future__ import annotations

import random

from locust import HttpUser, between, task

PROMPTS = [
    "Explain PagedAttention in one sentence.",
    "What is the difference between static and continuous batching?",
    "Summarize why circuit breakers matter in distributed systems.",
    "What does KV-cache mean for LLM inference?",
    "Write a two-sentence explanation of horizontal pod autoscaling.",
]


class InferMeshUser(HttpUser):
    wait_time = between(0.2, 1.0)

    @task
    def completion(self):
        prompt = random.choice(PROMPTS)
        with self.client.post(
            "/v1/completions",
            json={"prompt": prompt, "max_tokens": 128},
            catch_response=True,
        ) as resp:
            if resp.status_code == 503:
                # Expected under overload once backpressure kicks in — a
                # 503 here is the system behaving correctly, not a bug.
                resp.success()
            elif resp.status_code != 200:
                resp.failure(f"unexpected status {resp.status_code}")

    @task(1)
    def check_status(self):
        self.client.get("/status")
