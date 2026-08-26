"""
Tests streamlit_app/app.py's call_completion() — the one piece of the
Streamlit UI that's meaningfully unit-testable without a running Streamlit
session (everything else is UI rendering, exercised manually/visually
instead, which is the normal scope boundary for this kind of app).
"""

from unittest.mock import MagicMock, patch

import httpx

from streamlit_app.app import call_completion


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_successful_completion_returns_ok_outcome():
    fake_response = _mock_response(
        json_data={
            "text": "Paris.",
            "backend": "mock",
            "replica_id": "mock-0",
            "latency_ms": 142.5,
        }
    )
    with patch("httpx.post", return_value=fake_response):
        outcome = call_completion("http://localhost:8000", "capital of France?", 32)

    assert outcome.ok is True
    assert outcome.text == "Paris."
    assert outcome.backend == "mock"
    assert outcome.replica_id == "mock-0"
    assert outcome.backend_latency_ms == 142.5
    assert outcome.round_trip_ms >= 0


def test_http_error_returns_not_ok_with_message():
    fake_response = _mock_response(status_code=503, text="no healthy replica available")
    with patch("httpx.post", return_value=fake_response):
        outcome = call_completion("http://localhost:8000", "test", 32)

    assert outcome.ok is False
    assert "503" in outcome.error


def test_connection_error_returns_not_ok_with_message():
    with patch("httpx.post", side_effect=httpx.ConnectError("connection refused")):
        outcome = call_completion("http://localhost:9999", "test", 32)

    assert outcome.ok is False
    assert "localhost:9999" in outcome.error
