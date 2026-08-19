#!/usr/bin/env bash
# Chaos test #2: kill a real gateway pod in Kubernetes and confirm the
# Deployment replaces it, the PodDisruptionBudget is respected, and
# requests routed to the Service don't fail (assuming replicaCount >= 2).
#
# Usage:
#   ./chaos/kill_k8s_pod.sh <namespace> <release-name>
#
# Record in chaos/RESULTS.md: how many requests failed during the kill
# (measured via a concurrent loadtest run), how long until the replacement
# pod is Ready, and whether the PDB blocked a voluntary eviction correctly.

set -euo pipefail

NAMESPACE="${1:?usage: kill_k8s_pod.sh <namespace> <release-name>}"
RELEASE="${2:?usage: kill_k8s_pod.sh <namespace> <release-name>}"

echo "== Pods before =="
kubectl get pods -n "$NAMESPACE" -l app=infermesh-gateway -o wide

TARGET_POD=$(kubectl get pods -n "$NAMESPACE" -l app=infermesh-gateway \
  -o jsonpath='{.items[0].metadata.name}')

echo "== Killing pod: $TARGET_POD =="
kubectl delete pod "$TARGET_POD" -n "$NAMESPACE"

echo "== Watching replacement come up (ctrl-c to stop watching) =="
kubectl get pods -n "$NAMESPACE" -l app=infermesh-gateway -w
