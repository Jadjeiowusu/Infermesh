"""
InferMesh Control Room: a Streamlit front end for the gateway. Not just a
chat box — a live view into how the platform is behaving, and a way to
break it on purpose and watch it recover.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx
import pandas as pd
import streamlit as st

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000")

st.set_page_config(page_title="InferMesh Control Room", layout="wide")
st.title("InferMesh Control Room")


@dataclass
class CompletionOutcome:
    ok: bool
    text: str = ""
    backend: str = ""
    replica_id: str = ""
    backend_latency_ms: float = 0.0
    round_trip_ms: float = 0.0
    error: str = ""


def call_completion(gateway_url: str, prompt: str, max_tokens: int,
                     timeout: float = 30.0) -> CompletionOutcome:
    """
    Shared by the Playground and A/B Compare tabs, so both tabs measure
    and report the same way rather than duplicating the request/timing
    logic twice. Returns a result object either way (success or error)
    instead of raising, since both callers need to render something for
    either outcome rather than crash the whole page.
    """
    start = time.perf_counter()
    try:
        resp = httpx.post(
            f"{gateway_url}/v1/completions",
            json={"prompt": prompt, "max_tokens": max_tokens},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        round_trip_ms = (time.perf_counter() - start) * 1000
        return CompletionOutcome(
            ok=True,
            text=data["text"],
            backend=data["backend"],
            replica_id=data["replica_id"],
            backend_latency_ms=data["latency_ms"],
            round_trip_ms=round_trip_ms,
        )
    except httpx.HTTPStatusError as exc:
        return CompletionOutcome(
            ok=False, error=f"Gateway returned {exc.response.status_code}: {exc.response.text}"
        )
    except httpx.RequestError as exc:
        return CompletionOutcome(ok=False, error=f"Could not reach {gateway_url}: {exc}")


tab_playground, tab_ab_compare, tab_status, tab_chaos = st.tabs(
    ["Playground", "A/B Compare", "Live Status", "Chaos"]
)

with tab_playground:
    st.subheader("Send a completion request")
    prompt = st.text_area("Prompt", value="Explain PagedAttention in one sentence.")
    max_tokens = st.slider("Max tokens", min_value=8, max_value=512, value=128)

    if st.button("Run", type="primary"):
        outcome = call_completion(GATEWAY_URL, prompt, max_tokens)
        if outcome.ok:
            col1, col2, col3 = st.columns(3)
            col1.metric("Served by", outcome.replica_id)
            col2.metric("Backend latency (ms)", f"{outcome.backend_latency_ms:.0f}")
            col3.metric("Round-trip (ms)", f"{outcome.round_trip_ms:.0f}")
            st.text_area("Response", value=outcome.text, height=150)
        else:
            st.error(outcome.error)

with tab_ab_compare:
    st.subheader("Compare two gateways side by side")
    st.caption(
        "Send the same prompt to two different gateway instances and compare "
        "response, backend, and latency. Useful for e.g. mock vs. real vLLM, "
        "or two differently-configured real backends (see docs/LOCAL_GPU_SETUP.md "
        "and docs/LOCAL_CPU_SETUP.md for running more than one gateway locally)."
    )

    col_a_url, col_b_url = st.columns(2)
    gateway_a = col_a_url.text_input("Gateway A URL", value=GATEWAY_URL)
    gateway_b = col_b_url.text_input("Gateway B URL", value="http://localhost:9000")

    ab_prompt = st.text_area(
        "Prompt", value="Explain PagedAttention in one sentence.", key="ab_prompt"
    )
    ab_max_tokens = st.slider("Max tokens", min_value=8, max_value=512, value=128, key="ab_tokens")

    if st.button("Run comparison", type="primary"):
        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown(f"**Gateway A** — `{gateway_a}`")
            outcome_a = call_completion(gateway_a, ab_prompt, ab_max_tokens)
            if outcome_a.ok:
                st.metric("Backend", outcome_a.backend)
                st.metric("Backend latency (ms)", f"{outcome_a.backend_latency_ms:.0f}")
                st.metric("Round-trip (ms)", f"{outcome_a.round_trip_ms:.0f}")
                st.text_area("Response A", value=outcome_a.text, height=150, key="resp_a")
            else:
                st.error(outcome_a.error)

        with col_b:
            st.markdown(f"**Gateway B** — `{gateway_b}`")
            outcome_b = call_completion(gateway_b, ab_prompt, ab_max_tokens)
            if outcome_b.ok:
                st.metric("Backend", outcome_b.backend)
                st.metric("Backend latency (ms)", f"{outcome_b.backend_latency_ms:.0f}")
                st.metric("Round-trip (ms)", f"{outcome_b.round_trip_ms:.0f}")
                st.text_area("Response B", value=outcome_b.text, height=150, key="resp_b")
            else:
                st.error(outcome_b.error)

        if outcome_a.ok and outcome_b.ok:
            delta_ms = outcome_a.round_trip_ms - outcome_b.round_trip_ms
            faster = "A" if delta_ms > 0 else "B"
            st.info(
                f"Gateway {faster} was faster by {abs(delta_ms):.0f}ms round-trip "
                f"({outcome_a.backend} vs {outcome_b.backend})."
            )

with tab_status:
    st.subheader("Replica status")
    st.caption("Auto-refresh by re-running this tab; live in a future pass via st.autorefresh.")
    if st.button("Refresh status"):
        try:
            resp = httpx.get(f"{GATEWAY_URL}/status", timeout=5)
            resp.raise_for_status()
            replicas = resp.json()["replicas"]
            df = pd.DataFrame(replicas)
            st.dataframe(df, use_container_width=True)
        except httpx.RequestError as exc:
            st.error(f"Could not reach gateway at {GATEWAY_URL}: {exc}")

    st.markdown(
        f"Raw Prometheus metrics: [`{GATEWAY_URL}/metrics/`]({GATEWAY_URL}/metrics/) · "
        "Grafana dashboard: see `observability/grafana-dashboards/`."
    )

with tab_chaos:
    st.subheader("Break it on purpose")
    st.caption(
        "Kills a mock replica's health so you can watch the router's circuit "
        "breaker route around it, then bring it back. Real-replica chaos "
        "(killing a pod) lives in `chaos/` and is meant to run against k8s."
    )
    try:
        resp = httpx.get(f"{GATEWAY_URL}/status", timeout=5)
        resp.raise_for_status()
        replica_ids = [r["replica_id"] for r in resp.json()["replicas"]]
    except httpx.RequestError:
        replica_ids = []

    if replica_ids:
        target = st.selectbox("Replica", replica_ids)
        c1, c2 = st.columns(2)
        if c1.button("Kill replica", type="secondary"):
            httpx.post(f"{GATEWAY_URL}/admin/chaos/{target}/kill", timeout=5)
            st.warning(f"{target} marked unhealthy. Send a few completions and watch "
                       "`/status` — the circuit breaker should route around it.")
        if c2.button("Revive replica"):
            httpx.post(f"{GATEWAY_URL}/admin/chaos/{target}/revive", timeout=5)
            st.success(f"{target} marked healthy again.")
    else:
        st.info(f"Could not reach gateway at {GATEWAY_URL} to list replicas.")
