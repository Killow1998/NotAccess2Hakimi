"""Tests for admin config management API."""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from hakimi_proxy.auth import BearerAuthMiddleware
from hakimi_proxy.config import ProxyConfig
from hakimi_proxy.main import create_app
from hakimi_proxy.metering.store import UsageStore
from hakimi_proxy.pool import CredentialPool
from hakimi_proxy.adapters.aistudio import AIStudioAdapter
from hakimi_proxy.adapters.antigravity import AntigravityAdapter


def _make_admin_app():
    app = create_app()
    app.user_middleware.clear()
    app.add_middleware(BearerAuthMiddleware, auth_token="")
    app.state.pool = CredentialPool()
    app.state.store = UsageStore(Path(tempfile.gettempdir()) / "hakimi_test_admin.db")
    app.state.aistudio = AIStudioAdapter()
    app.state.antigravity = AntigravityAdapter()
    app.state.max_retries = 3
    app.state.config = ProxyConfig()
    return app


def test_get_config():
    app = _make_admin_app()
    client = TestClient(app)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "host" in data
    assert "port" in data
    assert "auth_token" in data


def test_update_settings():
    app = _make_admin_app()
    client = TestClient(app)
    resp = client.put("/api/config", json={
        "host": "0.0.0.0",
        "port": 9090,
        "auth_token": "newtoken",
        "max_retries": 5,
        "cooldown_seconds": 30,
        "db_path": "test.db",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert app.state.config.host == "0.0.0.0"
    assert app.state.config.port == 9090
    assert app.state.config.max_retries == 5


def test_add_aistudio_credential():
    app = _make_admin_app()
    client = TestClient(app)
    resp = client.post("/api/credentials/aistudio", json={
        "id": "test-1",
        "api_key": "AIzaSy-test",
        "project": "proj-1",
        "account": "user@gmail.com",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert len(app.state.config.aistudio_credentials) == 1
    assert app.state.config.aistudio_credentials[0].id == "test-1"
    assert len(app.state.pool.all_credentials) == 1


def test_duplicate_id_rejected():
    app = _make_admin_app()
    client = TestClient(app)
    client.post("/api/credentials/aistudio", json={"id": "dup", "api_key": "k1"})
    resp = client.post("/api/credentials/aistudio", json={"id": "dup", "api_key": "k2"})
    assert resp.status_code == 409


def test_delete_aistudio_credential():
    app = _make_admin_app()
    client = TestClient(app)
    client.post("/api/credentials/aistudio", json={"id": "to-delete", "api_key": "k"})
    resp = client.delete("/api/credentials/aistudio/to-delete")
    assert resp.status_code == 200
    assert len(app.state.config.aistudio_credentials) == 0


def test_delete_not_found():
    app = _make_admin_app()
    client = TestClient(app)
    resp = client.delete("/api/credentials/aistudio/nonexistent")
    assert resp.status_code == 404


def test_add_antigravity_credential():
    app = _make_admin_app()
    client = TestClient(app)
    resp = client.post("/api/credentials/antigravity", json={
        "id": "ag-1",
        "client_id": "cid",
        "client_secret": "cs",
        "refresh_token": "rt",
    })
    assert resp.status_code == 200
    assert len(app.state.config.antigravity_credentials) == 1


def test_list_credentials():
    app = _make_admin_app()
    client = TestClient(app)
    client.post("/api/credentials/aistudio", json={"id": "ai1", "api_key": "AIzaSy-test123"})
    client.post("/api/credentials/antigravity", json={
        "id": "ag1", "client_id": "cid", "client_secret": "cs", "refresh_token": "rt",
    })
    resp = client.get("/api/credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["aistudio"]) == 1
    assert len(data["antigravity"]) == 1
    assert "..." in data["aistudio"][0]["api_key"]
    assert data["aistudio"][0]["kind"] == "aistudio"
    assert data["antigravity"][0]["kind"] == "antigravity"


def test_usage_summary():
    app = _make_admin_app()
    client = TestClient(app)
    resp = client.get("/api/usage/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_requests"] == 0
    assert data["total_cost_usd"] == 0
    assert isinstance(data["by_credential"], list)
    assert isinstance(data["by_model"], list)


def test_web_ui_served():
    app = _make_admin_app()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "hakimi" in resp.text.lower()
    resp2 = client.get("/ui")
    assert resp2.status_code == 200
