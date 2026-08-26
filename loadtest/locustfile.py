"""
Load test the gateway's /v1/completions endpoint. Used in Phase 5 to
produce the before/after tables in docs/BENCHMARKS.md.

Run locally (normal load shape, InferMeshUser — realistic pacing):
    locust -f loadtest/locustfile.py --host http://localhost:8000

Headless, for scripted benchmark runs (e.g. 50 concurrent users for 60s):
    locust -f loadtest/locustfile.py --host http://localhost:8000 \
        --users 50 --spawn-rate 10 --run-time 60s --headless \
        --csv loadtest/results/run_50users

Run the burst/backpressure test instead (BurstUser — no wait between
requests, meant to actually exceed the router's concurrent-request cap
and trigger 503s — see docs/BENCHMARKS.md's Phase 5 entry on why
InferMeshUser's realistic pacing never does this even at 100 users):
    locust -f loadtest/locustfile.py BurstUser --host http://localhost:8000 \
        --users 30 --spawn-rate 30 --run-time 20s --headless \
        --csv loadtest/results/run_burst_30
"""

from __future__ import annotations

import random

from locust import HttpUser, between, constant, task

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


class BurstUser(HttpUser):
    """
    No wait_time between requests — each simulated user re-issues
    immediately after its previous request completes, instead of pausing.
    This is what actually pushes real concurrent in-flight requests above
    the router's backpressure cap (max_in_flight_per_replica × replica
    count) — InferMeshUser's realistic 0.2-1.0s pacing never does this
    even at 100 simulated users, confirmed in docs/BENCHMARKS.md via
    Little's Law (concurrency ≈ throughput × service time stayed ~10-11
    at 100 users, well under the cap of 20).
    """
    wait_time = constant(0)

    @task
    def completion(self):
        prompt = random.choice(PROMPTS)
        with self.client.post(
            "/v1/completions",
            json={"prompt": prompt, "max_tokens": 128},
            catch_response=True,
        ) as resp:
            if resp.status_code == 503:
                resp.success()
            elif resp.status_code != 200:
                resp.failure(f"unexpected status {resp.status_code}")
