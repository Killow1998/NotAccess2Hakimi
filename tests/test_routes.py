"""Integration tests for API routes using FastAPI TestClient."""

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from hakimi_proxy.config import AIStudioCredential, ProxyConfig
from hakimi_proxy.main import create_app
from hakimi_proxy.pool import CredentialPool
from hakimi_proxy.adapters.aistudio import AIStudioAdapter
from hakimi_proxy.adapters.antigravity import AntigravityAdapter
from hakimi_proxy.metering.store import UsageStore


def _make_app_with_state():
    """Create an app with a pre-populated pool and temp DB."""
    app = create_app()
    # Disable auth for tests
    from hakimi_proxy.auth import BearerAuthMiddleware
    app.user_middleware.clear()
    app.add_middleware(BearerAuthMiddleware, auth_token="")
    # Override app state with test data
    pool = CredentialPool(cooldown_seconds=60)
    pool.add_aistudio(AIStudioCredential(id="test-ai", api_key="fake-key"))
    app.state.pool = pool
    app.state.store = UsageStore(Path(tempfile.gettempdir()) / "hakimi_test_routes.db")
    app.state.aistudio = AIStudioAdapter()
    app.state.antigravity = AntigravityAdapter()
    app.state.max_retries = 3
    app.state.config = ProxyConfig()
    return app


def test_healthz():
    app = _make_app_with_state()
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["total_credentials"] == 1


def test_list_models():
    app = _make_app_with_state()
    client = TestClient(app)
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    model_ids = [m["id"] for m in data["data"]]
    assert "gemini-3.7-flash" in model_ids


def test_credentials_status():
    app = _make_app_with_state()
    client = TestClient(app)
    resp = client.get("/v1/credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["credentials"]) == 1
    assert data["credentials"][0]["id"] == "test-ai"
    assert data["credentials"][0]["state"] == "active"


def test_usage_empty():
    app = _make_app_with_state()
    client = TestClient(app)
    resp = client.get("/v1/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total_requests"] == 0
    assert data["records"] == []


def test_auth_rejects_no_token():
    """When auth_token is set, requests without Bearer are rejected."""
    app = create_app()
    # Manually set auth token by recreating middleware
    from hakimi_proxy.auth import BearerAuthMiddleware
    app.user_middleware.clear()
    app.add_middleware(BearerAuthMiddleware, auth_token="secret123")
    app.state.pool = CredentialPool()
    client = TestClient(app)

    # /healthz is public
    resp = client.get("/healthz")
    assert resp.status_code == 200

    # /v1/models requires auth
    resp = client.get("/v1/models")
    assert resp.status_code == 401

    # With correct token
    resp = client.get("/v1/models", headers={"Authorization": "Bearer secret123"})
    assert resp.status_code == 200


def test_chat_no_credentials_returns_503():
    """With no available credentials, returns 503."""
    app = create_app()
    from hakimi_proxy.auth import BearerAuthMiddleware
    app.user_middleware.clear()
    app.add_middleware(BearerAuthMiddleware, auth_token="")
    app.state.pool = CredentialPool()
    app.state.config = ProxyConfig()
    client = TestClient(app)
    resp = client.post("/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert resp.status_code == 503
    assert "exhausted" in resp.json()["error"]["message"]
