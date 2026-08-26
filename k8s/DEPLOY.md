# Deploying InferMesh to Kubernetes

Phases 0-2 ran on your own machine directly or via `docker compose`. This
is Phase 3: the same gateway + consumer + Kafka/Zookeeper, deployed to a
real (local) Kubernetes cluster via the Helm chart in
`k8s/helm/infermesh/`, so the reliability story (PodDisruptionBudget, a
real pod getting killed and replaced) is tested against actual
Kubernetes behavior instead of the mock-backend chaos test from Phase 0.

**Scope note:** this phase deploys the gateway, consumer, and a
demo-scoped Kafka/Zookeeper — it does **not** deploy Prometheus/Grafana
to the cluster. Those stay in `docker compose` from Phase 2. Running a
real observability stack in-cluster is normally done via
`kube-prometheus-stack`, which is its own significant piece of scope —
noted as a gap rather than attempted halfway.

## 1. Install minikube

Docker is already installed (from Phase 2), so the Docker driver is the
simplest option — no separate VM layer needed.

```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
minikube start --driver=docker
```

Also grab `kubectl` if you don't have it:

```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/kubectl
kubectl get nodes   # should show one Ready node
```

And Helm:

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

## 2. Build images into minikube's Docker daemon

Minikube runs its own Docker daemon, separate from the one you've been
using for `docker compose`. Point your shell at it before building, so
images land where minikube can actually see them (skipping this is the
single most common cause of `ImagePullBackOff` with local images):

```bash
eval $(minikube docker-env)
docker build -f docker/Dockerfile.gateway -t infermesh-gateway:latest .
docker build -f docker/Dockerfile.consumer -t infermesh-consumer:latest .
```

(Run `eval $(minikube docker-env)` in every new terminal where you plan
to build images for minikube — it only affects the current shell.)

## 3. Install the chart

```bash
helm install infermesh k8s/helm/infermesh
```

Watch it come up:

```bash
kubectl get pods -w
```

You should see `infermesh-gateway-*` (2 pods), `infermesh-consumer-*` (1
pod), `infermesh-kafka-*`, and `infermesh-zookeeper-*` reach `Running`.
Kafka can take 20-30s to become ready after Zookeeper does — the gateway
pods may show a few restarts early on if they start before Kafka does;
that's expected and self-resolves (the `EventEmitter`'s fail-soft design
from Phase 0 means the app itself doesn't crash on this, but the pod's
own startup ordering isn't guaranteed by Helm without an initContainer,
which isn't in scope here — another honest gap, not a blocker).

## 4. Verify it actually works

```bash
kubectl port-forward svc/infermesh-gateway 8000:8000
```

In another terminal:

```bash
curl -X POST http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"prompt": "hello from kubernetes", "max_tokens": 32}'
```

Same response shape as every other phase — `backend`, `replica_id`,
`latency_ms` — just now served from a pod instead of a bare process.

## 5. Run the chaos test

The same reliability claim from Phase 0's mock-backend chaos test, now
against a real Kubernetes Deployment instead of an in-process health
flag:

```bash
./chaos/kill_k8s_pod.sh default infermesh
```

While that's running, hit the gateway repeatedly from a third terminal
(via the port-forward from step 4) and watch whether any request fails
during the kill/replace window. Full results, including the exact
commands used and the request-loop output, are in `chaos/RESULTS.md`
Test 2: 40/40 requests returned HTTP 200 during an actual pod deletion,
with the replacement pod reaching Ready in ~8 seconds.

## 6. Confirm the PodDisruptionBudget is real, not decorative

```bash
kubectl get pdb
```

Note the `ALLOWED DISRUPTIONS` column — the disruption controller
computes it live from current replica count and `minAvailable`.

A dry-run drain is not a reliable way to test this — it doesn't mutate
cluster state between simulated evictions, so it can report both
replicas of a 2-pod Deployment as evictable even when a real drain would
correctly reject the second one. Use a real drain instead:

```bash
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data --force
```

On a single-node cluster this evicts everything on the node, including
both gateway pods — the first evicts normally, the second is rejected
with the PDB's actual eviction-API error
(`chaos/RESULTS.md` Test 3 has the full output). Run
`kubectl uncordon <node-name>` afterward to let everything reschedule.

## Canary rollout

Disabled by default. To try it:

```bash
helm upgrade infermesh k8s/helm/infermesh \
  --set gateway.canary.enabled=true \
  --set gateway.canary.replicaCount=1
```

This adds one canary pod (`infermesh-gateway-canary-*`) sharing the same
Service as the main gateway Deployment — so roughly 1-in-3 requests (1
canary pod among 3 total, with the default `replicaCount: 2` for the main
Deployment) land on the canary. This is a **basic, honest
vanilla-Kubernetes canary** — traffic split by pod count, not an exact
weighted percentage, and with no automated rollback logic. A real
progressive-delivery setup (exact traffic percentages, automatic rollback
on error-rate regression) needs a tool like Argo Rollouts or Flagger —
out of scope here, and worth saying so plainly rather than overclaiming
what this does.

## Known gaps (tracked, not hidden)

- No Prometheus/Grafana in-cluster (see scope note above)
- HPA still scales on CPU, not the custom `infermesh_replica_in_flight`
  metric — see the comment in `values.yaml` under `gateway.autoscaling`
- Kafka/Zookeeper are single-replica, no persistent storage — fine for a
  demo, not how you'd run them for real
- The consumer's Kafka connection retries with backoff
  (`wait_for_kafka_and_start()`, tested in
  `tests/test_kafka_consumer_retry.py`) rather than crashing if Kafka
  isn't ready yet at pod startup — a real startup-ordering race on first
  deploy caused `CrashLoopBackOff` before this was in place. The
  gateway's `EventEmitter` needed no equivalent fix: it's fail-soft by
  design, so a request is served without an emitted event if Kafka isn't
  up yet.

## Tearing down

```bash
helm uninstall infermesh
minikube stop
```
