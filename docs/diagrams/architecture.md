# Architecture Diagram

GitHub renders Mermaid natively in Markdown — no image export needed.

```mermaid
flowchart TB
    subgraph Client
        SL[Streamlit Control Room]
    end

    subgraph Gateway
        GW[FastAPI Gateway<br/>router: LB + retries + circuit breaker]
    end

    subgraph Replicas
        R1[Model Replica 1<br/>mock / llama.cpp / vLLM]
        R2[Model Replica 2<br/>mock / llama.cpp / vLLM]
    end

    subgraph EventPipeline[Event Pipeline]
        K[(Kafka topic:<br/>inference.events)]
        C[Metrics Consumer]
    end

    subgraph Observability
        P[Prometheus]
        G[Grafana]
    end

    SL -->|HTTP| GW
    GW --> R1
    GW --> R2
    GW -->|emit event, best-effort| K
    K --> C
    GW -->|/metrics| P
    C -->|/metrics| P
    P --> G

    subgraph K8s[Kubernetes]
        HPA[HPA] -.scales.-> GW
        PDB[PodDisruptionBudget] -.protects.-> GW
    end
```

## Request flow (happy path)

1. Streamlit (or any client) posts a prompt to the gateway's
   `/v1/completions`.
2. The router picks the replica with the fewest in-flight requests among
   healthy ones.
3. On failure, the router retries once against a different replica; three
   consecutive failures on a replica trips its circuit breaker for a
   cooldown window.
4. The completion result is returned to the client, and — independently,
   best-effort — an event is emitted to Kafka.
5. The metrics consumer aggregates events into Prometheus metrics;
   Grafana reads from Prometheus.

## Failure mode this diagram is meant to make obvious

If Kafka is down, the request path (client → gateway → replica → client)
is completely unaffected — only the dotted-line observability path
degrades. This is verified in practice, not just claimed: see the gateway
startup log in `chaos/RESULTS.md`'s Phase 0 notes.
