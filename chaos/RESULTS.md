# Chaos Test Results

## Test 1: kill a mock replica (`chaos/kill_mock_replica.sh`)

**Setup:** gateway running with `MODEL_BACKEND=mock`, `N_MOCK_REPLICAS=2`
(`mock-0`, `mock-1`), `failure_threshold=3`, `cooldown_seconds=15`.

**Run:**
```
./chaos/kill_mock_replica.sh mock-0 http://localhost:8003
```

**Observed:**
1. Before: both replicas healthy, `circuit_open: false`.
2. Killed `mock-0` via `/admin/chaos/mock-0/kill`.
3. Sent 5 completion requests — **all 5 served by `mock-1`, zero failures
   visible to the caller.** The router's retry-against-a-different-replica
   logic absorbed the failing replica transparently.
4. After: `/status` shows `mock-0` with `circuit_open: true`,
   `consecutive_failures: 3` — the breaker tripped exactly at the
   configured threshold, without needing all 5 requests to hit it (the
   first request against `mock-0` fails, retries onto `mock-1`, and that
   failure counts toward the threshold even though the caller never saw
   an error).
5. Revived `mock-0` — `set_healthy(True)` clears it for the router to
   pick up again once `open_until` passes (or immediately, since revive
   doesn't reset `open_until` in this version — see "Known gap" below).

**Conclusion:** the core reliability claim — "one replica going down
should not cause visible request failures" — holds. This is the mock
version of the story; Phase 3 repeats this exact test against real k8s
pods (`chaos/kill_k8s_pod.sh`) to prove the same property survives an
actual pod restart, not just an in-process health flag.

**Known gap to fix in Phase 3:** `revive` sets the mock backend healthy
immediately but doesn't clear `open_until` on the router side, so a revived
replica could still be skipped for the remainder of its cooldown window.
Low-priority since the cooldown is short (15s) and the real k8s chaos test
uses actual pod readiness instead — noting it here so it isn't lost.

## Test 2: kill a real k8s pod (`chaos/kill_k8s_pod.sh`)

Not yet run — requires the Helm chart deployed to a cluster (Phase 3).
Planned measurement: run `loadtest/locustfile.py` concurrently, kill a
gateway pod mid-run, and report request failure count during the window
between kill and replacement-pod-Ready, plus whether the PDB blocked a
simultaneous `kubectl drain`.
