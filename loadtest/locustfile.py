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

from locust import HttpUser, between, constant, events, task

PROMPTS = [
    "Explain PagedAttention in one sentence.",
    "What is the difference between static and continuous batching?",
    "Summarize why circuit breakers matter in distributed systems.",
    "What does KV-cache mean for LLM inference?",
    "Write a two-sentence explanation of horizontal pod autoscaling.",
]


def do_completion(user: HttpUser) -> None:
    """
    Shared by both user classes below. On a 503 (expected once the
    router's backpressure cap is hit — see serving/backend.py and
    gateway/app/router.py), marks the response as successful (a 503 here
    is the system behaving correctly, not a load-test failure) but ALSO
    fires a separately-named request event, so 503s show up as their own
    row in Locust's stats table instead of being silently folded into the
    200 count. An earlier version of this file only did the former —
    which technically made "# fails" always read 0 whether or not
    backpressure was actually triggered, hiding the exact thing the test
    was meant to measure. See docs/BENCHMARKS.md's Phase 5 burst-test
    entry for the real numbers this was built to catch.
    """
    prompt = random.choice(PROMPTS)
    with user.client.post(
        "/v1/completions",
        json={"prompt": prompt, "max_tokens": 128},
        catch_response=True,
    ) as resp:
        if resp.status_code == 503:
            resp.success()
            events.request.fire(
                request_type="POST",
                name="/v1/completions [503 backpressure]",
                response_time=resp.elapsed.total_seconds() * 1000,
                response_length=len(resp.content),
                exception=None,
                context={},
            )
        elif resp.status_code != 200:
            resp.failure(f"unexpected status {resp.status_code}")


class InferMeshUser(HttpUser):
    wait_time = between(0.2, 1.0)

    @task
    def completion(self):
        do_completion(self)

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
        do_completion(self)
