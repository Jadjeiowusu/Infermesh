# Chaos Test Results

## Summary

| # | Test | Claim tested | Result |
|---|---|---|---|
| 1 | Kill a mock replica | Router routes around a failing replica with zero visible failures | **Met** — 5/5 requests succeeded, circuit breaker tripped at the configured threshold |
| 2 | Kill a real k8s pod | Same claim, against real Kubernetes pod churn, not an in-process flag | **Met** — 40/40 requests returned HTTP 200 during an actual pod deletion; replacement pod Ready in ~8s |
| 3 | `kubectl drain` (PodDisruptionBudget) | PDB actually blocks a voluntary eviction, not just configured to look like it does | **Met** — real Kubernetes eviction error (`Cannot evict pod as it would violate the pod's disruption budget`), confirmed after a misleading dry-run result was correctly diagnosed as a dry-run limitation, not a PDB failure |

Each test's full setup, exact commands, and complete observed output is
below — the summary above is for quick scanning, not a replacement for
the detail.

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

**Setup:** minikube (Docker driver), Helm chart installed with default
`values.yaml` (2 gateway replicas, mock backend, Kafka/Zookeeper
in-cluster). Gateway reached via `kubectl port-forward
svc/infermesh-gateway 8010:8000`.

**Run:**
```
# Terminal 1: 40 requests, one every 0.25s (~10s total), logging HTTP status
for i in $(seq 1 40); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8010/v1/completions \
    -H "Content-Type: application/json" -d '{"prompt": "chaos test", "max_tokens": 16}')
  echo "$i: HTTP $STATUS"; sleep 0.25
done

# Terminal 2, started ~1-2s into the loop above:
./chaos/kill_k8s_pod.sh default infermesh
```

**Observed:**
1. Before: 2 gateway pods, both `Running`/`1/1 Ready`.
2. `kill_k8s_pod.sh` deleted one pod (`infermesh-gateway-...-ddnpk`).
3. The other pod (`infermesh-gateway-...-kmhk6`) stayed `Running` the
   entire time — the Service never lost every healthy endpoint.
4. Kubernetes created a replacement pod (`infermesh-gateway-...-4fmvw`)
   immediately; on an earlier identical run (different pod killed), the
   replacement reached `1/1 Running` in **~8 seconds** from creation.
5. **Request loop result: 40/40 requests returned HTTP 200.** Zero
   failures, measured directly (not inferred from pod status) — this is
   the strongest reliability result in the project so far, because it's
   a real Kubernetes Service routing around a real pod deletion, not an
   in-process mock health flag (Test 1, above) or a simulated failure.

**Conclusion:** the reliability claim from Test 1 ("one replica going
down should not cause visible request failures") now holds against
actual Kubernetes pod churn, not just the mock backend. `readinessProbe`
+ the Service's endpoint list doing exactly what they're supposed to —
routing only to Ready pods — is what made this work, with zero extra
logic needed in the application itself.

**PodDisruptionBudget enforcement is tested separately in Test 3
below** — killing a pod directly (as this test does) bypasses the PDB
entirely, since PDBs only govern voluntary evictions.

## Test 3: PodDisruptionBudget enforcement (`kubectl drain`)

**Setup:** same cluster as Test 2, 2 gateway replicas, PDB
`minAvailable: 1`.

**First attempt — dry-run (misleading result, worth documenting why):**
```
kubectl drain minikube --ignore-daemonsets --delete-emptydir-data --force --dry-run=server
```
This reported **both** gateway pods as evictable, with no PDB objection.
That result is **wrong**, not a sign the PDB doesn't work — `--dry-run`
evictions don't mutate cluster state, so each pod's eviction check is
evaluated independently against the *same* unchanged "2 healthy" baseline.
A dry-run drain can't see the effect of its own prior (simulated)
evictions within the same run, so it can't actually reveal whether a PDB
would block the *second* of two evictions against the same budget. Worth
knowing this limitation exists before trusting a dry-run drain as proof
of anything sequential.

**Real test (no `--dry-run`):**
```
kubectl drain minikube --ignore-daemonsets --delete-emptydir-data --force
```
**Observed:** the first gateway pod evicted normally. The second was
rejected repeatedly:
```
error when evicting pods/"infermesh-gateway-...-4fmvw" -n "default" (will retry after 5s): Cannot evict pod as it would violate the pod's disruption budget.
```
It kept retrying every 5s indefinitely (correct — minikube is
single-node, cordoned during a drain, so there's genuinely nowhere for a
replacement to schedule and no way capacity recovers mid-drain). Manually
interrupted, then `kubectl uncordon minikube` restored the node; the
stack (gateway, Kafka, Zookeeper, consumer) rescheduled and recovered.

**Conclusion:** the PDB is real, not decorative — confirmed with the
actual expected Kubernetes eviction-API error message, not inferred.
`kubectl get pdb`'s live `ALLOWED DISRUPTIONS: 1` column (computed
continuously by the disruption controller) also independently corroborated
this before the drain test even ran.

**Side effect of this test:** draining fully recreated Kafka and
Zookeeper (both single-replica, no persistent storage — a known,
documented gap). The consumer pod that came up afterward crash-looped 3
times before stabilizing, because its Kafka connection had no retry
logic at that point. Fixed with `wait_for_kafka_and_start()` (retry with
backoff — see Phase 3 in `docs/ROADMAP.md` and
`tests/test_kafka_consumer_retry.py`); confirmed clean via a zero-restart
pod on redeploy.

