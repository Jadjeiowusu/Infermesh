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

**Not yet tested:** whether the PodDisruptionBudget (`minAvailable: 1`)
actually blocks a *voluntary* eviction (e.g. `kubectl drain`) — this test
used `kubectl delete pod` directly, which always succeeds regardless of
the PDB (PDBs only guard voluntary evictions, not direct deletion). See
`k8s/DEPLOY.md`'s `kubectl drain --dry-run=server` step for that separate
check, not yet run.

