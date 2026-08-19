"""
InferMesh Control Room: a Streamlit front end for the gateway. Not just a
chat box — a live view into how the platform is behaving, and a way to
break it on purpose and watch it recover.
"""

from __future__ import annotations

import os
import time

import httpx
import pandas as pd
import streamlit as st

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000")

st.set_page_config(page_title="InferMesh Control Room", layout="wide")
st.title("InferMesh Control Room")

tab_playground, tab_status, tab_chaos = st.tabs(
    ["Playground", "Live Status", "Chaos"]
)

with tab_playground:
    st.subheader("Send a completion request")
    prompt = st.text_area("Prompt", value="Explain PagedAttention in one sentence.")
    max_tokens = st.slider("Max tokens", min_value=8, max_value=512, value=128)

    if st.button("Run", type="primary"):
        start = time.perf_counter()
        try:
            resp = httpx.post(
                f"{GATEWAY_URL}/v1/completions",
                json={"prompt": prompt, "max_tokens": max_tokens},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            elapsed_ms = (time.perf_counter() - start) * 1000

            col1, col2, col3 = st.columns(3)
            col1.metric("Served by", data["replica_id"])
            col2.metric("Backend latency (ms)", f"{data['latency_ms']:.0f}")
            col3.metric("Round-trip (ms)", f"{elapsed_ms:.0f}")
            st.text_area("Response", value=data["text"], height=150)
        except httpx.HTTPStatusError as exc:
            st.error(f"Gateway returned {exc.response.status_code}: {exc.response.text}")
        except httpx.RequestError as exc:
            st.error(f"Could not reach gateway at {GATEWAY_URL}: {exc}")

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
