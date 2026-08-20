"""Tests for admin config management API."""

import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from httpx2 import ASGITransport, AsyncClient

from hakimi_proxy.auth import BearerAuthMiddleware
from hakimi_proxy.config import AIStudioCredential, ProxyConfig
from hakimi_proxy.main import create_app
from hakimi_proxy.metering.store import UsageStore
from hakimi_proxy.pool import CredentialPool
from hakimi_proxy.adapters.aistudio import AIStudioAdapter
from hakimi_proxy.adapters.antigravity import AntigravityAdapter
from hakimi_proxy.oauth import AntigravityOAuthBundle
from hakimi_proxy.routes import admin as admin_routes


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("HAKIMI_CONFIG", str(path))
    return path


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


async def _request(app, method, path, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


async def test_get_config():
    app = _make_admin_app()
    resp = await _request(app, "GET", "/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "host" in data
    assert "port" in data
    assert "auth_token" in data
    assert "proxy" in data
    assert data["proxy_source"] in {"config", "environment", "system", "direct", "unknown"}


async def test_list_credentials_exposes_runtime_status():
    app = _make_admin_app()
    credential = AIStudioCredential(id="runtime-ai", api_key="key")
    app.state.config.aistudio_credentials.append(credential)
    app.state.pool.add_aistudio(credential)

    resp = await _request(app, "GET", "/api/credentials")

    assert resp.status_code == 200
    runtime = next(item for item in resp.json()["aistudio"] if item["id"] == "runtime-ai")
    assert runtime["state"] == "active"
    assert runtime["health"] == "unknown"
    assert runtime["in_flight"] == 0
    assert runtime["last_error_type"] is None


async def test_update_settings():
    app = _make_admin_app()
    resp = await _request(app, "PUT", "/api/config", json={
        "host": "0.0.0.0",
        "port": 9090,
        "auth_token": "newtoken",
        "max_retries": 5,
        "cooldown_seconds": 30,
        "db_path": "test.db",
        "proxy": "socks5://127.0.0.1:1080",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert app.state.config.host == "0.0.0.0"
    assert app.state.config.port == 9090
    assert app.state.config.max_retries == 5
    assert app.state.config.proxy == "socks5://127.0.0.1:1080"
    assert resp.json()["proxy_source"] == "config"


async def test_add_aistudio_credential():
    app = _make_admin_app()
    resp = await _request(app, "POST", "/api/credentials/aistudio", json={
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


async def test_update_aistudio_preserves_omitted_secret():
    app = _make_admin_app()
    await _request(app, "POST", "/api/credentials/aistudio", json={
        "id": "ai-update",
        "api_key": "secret-key",
        "project": "old-project",
        "account": "old@example.com",
    })

    resp = await _request(app, "PUT", "/api/credentials/aistudio/ai-update", json={
        "project": "new-project",
        "account": "new@example.com",
    })

    assert resp.status_code == 200
    stored = app.state.config.aistudio_credentials[0]
    assert stored.api_key == "secret-key"
    assert stored.project == "new-project"
    assert stored.account == "new@example.com"


async def test_duplicate_id_rejected():
    app = _make_admin_app()
    await _request(app, "POST", "/api/credentials/aistudio", json={"id": "dup", "api_key": "k1"})
    resp = await _request(app, "POST", "/api/credentials/aistudio", json={"id": "dup", "api_key": "k2"})
    assert resp.status_code == 409


async def test_create_rejects_blank_required_secrets():
    app = _make_admin_app()
    ai = await _request(app, "POST", "/api/credentials/aistudio", json={"id": "blank-ai", "api_key": "  "})
    ag = await _request(app, "POST", "/api/credentials/antigravity", json={
        "id": "blank-ag", "client_id": "cid", "client_secret": "", "refresh_token": "rt",
    })
    assert ai.status_code == 422
    assert ag.status_code == 422
    assert not app.state.config.aistudio_credentials
    assert not app.state.config.antigravity_credentials


async def test_delete_aistudio_credential():
    app = _make_admin_app()
    await _request(app, "POST", "/api/credentials/aistudio", json={"id": "to-delete", "api_key": "k"})
    resp = await _request(app, "DELETE", "/api/credentials/aistudio/to-delete")
    assert resp.status_code == 200
    assert len(app.state.config.aistudio_credentials) == 0


async def test_delete_not_found():
    app = _make_admin_app()
    resp = await _request(app, "DELETE", "/api/credentials/aistudio/nonexistent")
    assert resp.status_code == 404


async def test_add_antigravity_credential(_isolate_config):
    app = _make_admin_app()
    resp = await _request(app, "POST", "/api/credentials/antigravity", json={
        "id": "ag-1",
        "client_id": "cid",
        "client_secret": "cs",
        "refresh_token": "rt",
        "project": "project-1",
        "auto_onboard": True,
    })
    assert resp.status_code == 200
    assert len(app.state.config.antigravity_credentials) == 1
    assert app.state.config.antigravity_credentials[0].project == "project-1"
    assert app.state.config.antigravity_credentials[0].auto_onboard is True
    assert _isolate_config.stat().st_mode & 0o777 == 0o600


async def test_antigravity_oauth_status_creates_credential(monkeypatch, _isolate_config):
    app = _make_admin_app()

    class OAuthStub:
        proxy = ""
        client_id = "client-id"
        client_secret = "client-secret"

        def snapshot(self, state):
            return {"status": "pending", "credential_id": "", "account": "", "message": ""}

        def claim_code(self, state):
            return "one-time-code", "http://localhost:51121/oauth-callback"

        def complete(self, state, credential_id, account):
            self.completed = (credential_id, account)

        def fail(self, state, message):
            raise AssertionError(message)

    app.state.antigravity_oauth = OAuthStub()

    async def fake_exchange(code, redirect_uri, proxy, client_id, client_secret):
        assert code == "one-time-code"
        return AntigravityOAuthBundle(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            access_token="access-token",
            expires_at=123.0,
            account="user@example.com",
        )

    monkeypatch.setattr(admin_routes, "exchange_oauth_code", fake_exchange)
    response = await _request(app, "GET", "/api/credentials/antigravity/oauth/status/state-1")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "credential_id": "antigravity-user-example.com",
        "account": "user@example.com",
    }
    stored = app.state.config.antigravity_credentials[0]
    assert stored.account == "user@example.com"
    assert stored.refresh_token == "refresh-token"
    assert "refresh-token" not in response.text


async def test_antigravity_oauth_start_returns_browser_session():
    app = _make_admin_app()
    app.state.antigravity_oauth = SimpleNamespace(start=lambda: {
        "status": "pending",
        "state": "state-1",
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?state=state-1",
        "expires_in": 300,
    })

    response = await _request(app, "POST", "/api/credentials/antigravity/oauth/start")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert "authorization_url" in response.json()


async def test_antigravity_oauth_complete_accepts_remote_callback(monkeypatch, _isolate_config):
    app = _make_admin_app()

    class OAuthStub:
        proxy = ""
        client_id = "client-id"
        client_secret = "client-secret"

        def snapshot(self, state):
            return {"status": "pending", "credential_id": "", "account": "", "message": ""}

        def record_manual_callback(self, state, callback_url="", code=""):
            assert state == "state-1"
            assert "code=one-time-code" in callback_url
            return True

        def claim_code(self, state):
            return "one-time-code", "http://localhost:51121/oauth-callback"

        def complete(self, state, credential_id, account):
            self.completed = (credential_id, account)

        def fail(self, state, message):
            raise AssertionError(message)

    app.state.antigravity_oauth = OAuthStub()

    async def fake_exchange(code, redirect_uri, proxy, client_id, client_secret):
        assert code == "one-time-code"
        return AntigravityOAuthBundle(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            access_token="access-token",
            expires_at=123.0,
            account="remote@example.com",
        )

    monkeypatch.setattr(admin_routes, "exchange_oauth_code", fake_exchange)
    response = await _request(app, "POST", "/api/credentials/antigravity/oauth/complete", json={
        "state": "state-1",
        "callback_url": "http://localhost:51121/oauth-callback?code=one-time-code&state=state-1",
    })

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert app.state.config.antigravity_credentials[0].account == "remote@example.com"


async def test_update_antigravity_preserves_omitted_oauth():
    app = _make_admin_app()
    await _request(app, "POST", "/api/credentials/antigravity", json={
        "id": "ag-update",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "refresh_token": "refresh-token",
        "project": "old-project",
    })
    stored = app.state.config.antigravity_credentials[0]
    stored.access_token = "cached-access-token"
    stored.expires_at = 123.0

    resp = await _request(app, "PUT", "/api/credentials/antigravity/ag-update", json={
        "project": "new-project",
        "auto_onboard": True,
    })

    assert resp.status_code == 200
    stored = app.state.config.antigravity_credentials[0]
    assert stored.client_id == "client-id"
    assert stored.client_secret == "client-secret"
    assert stored.refresh_token == "refresh-token"
    assert stored.access_token == "cached-access-token"
    assert stored.expires_at == 123.0
    assert stored.project == "new-project"
    assert stored.auto_onboard is True


async def test_update_antigravity_identity_change_clears_cached_state():
    app = _make_admin_app()
    await _request(app, "POST", "/api/credentials/antigravity", json={
        "id": "ag-rotate",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "refresh_token": "refresh-token",
        "project": "old-project",
    })
    stored = app.state.config.antigravity_credentials[0]
    stored.access_token = "cached-access-token"
    stored.expires_at = 123.0

    resp = await _request(app, "PUT", "/api/credentials/antigravity/ag-rotate", json={
        "refresh_token": "new-refresh-token",
    })

    assert resp.status_code == 200
    stored = app.state.config.antigravity_credentials[0]
    assert stored.refresh_token == "new-refresh-token"
    assert stored.access_token == ""
    assert stored.expires_at == 0.0
    assert stored.project == ""


async def test_list_credentials():
    app = _make_admin_app()
    await _request(app, "POST", "/api/credentials/aistudio", json={"id": "ai1", "api_key": "AIzaSy-test123"})
    await _request(app, "POST", "/api/credentials/antigravity", json={
        "id": "ag1", "client_id": "cid", "client_secret": "cs", "refresh_token": "rt",
    })
    resp = await _request(app, "GET", "/api/credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["aistudio"]) == 1
    assert len(data["antigravity"]) == 1
    assert data["aistudio"][0]["api_key_set"] is True
    assert "api_key" not in data["aistudio"][0]
    assert data["aistudio"][0]["kind"] == "aistudio"
    assert data["antigravity"][0]["kind"] == "antigravity"
    assert data["antigravity"][0]["client_id"] == "cid"
    assert data["antigravity"][0]["client_secret_set"] is True
    assert data["antigravity"][0]["refresh_token_set"] is True
    assert "refresh_token" not in data["antigravity"][0]
    assert "AIzaSy-test123" not in resp.text


async def test_antigravity_credential_connection():
    app = _make_admin_app()
    await _request(app, "POST", "/api/credentials/antigravity", json={
        "id": "ag-test", "client_id": "cid", "client_secret": "cs", "refresh_token": "rt",
    })

    async def forward(body, cred, stream, client):
        assert cred.id == "ag-test"
        assert body["model"] == "antigravity/gemini-3.7-flash-tiered"
        assert stream is False
        return httpx.Response(200, json={"response": {}})

    app.state.antigravity.forward = forward
    resp = await _request(app, "POST", "/api/credentials/antigravity/ag-test/test")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["credential_id"] == "ag-test"
    assert data["provider"] == "antigravity"
    assert data["model"] == "antigravity/gemini-3.7-flash-tiered"
    assert isinstance(data["latency_ms"], int)


async def test_credential_connection_names_empty_timeout():
    app = _make_admin_app()
    await _request(app, "POST", "/api/credentials/antigravity", json={
        "id": "ag-timeout", "client_id": "cid", "client_secret": "cs", "refresh_token": "rt",
    })

    async def forward(body, cred, stream, client):
        raise httpx.ConnectTimeout("")

    app.state.antigravity.forward = forward
    resp = await _request(app, "POST", "/api/credentials/antigravity/ag-timeout/test")

    assert resp.status_code == 502
    assert resp.json()["error"]["type"] == "upstream_transport_error"
    assert "ConnectTimeout" in resp.json()["error"]["message"]


async def test_credential_connection_upstream_429_exposes_safe_reason():
    app = _make_admin_app()
    await _request(app, "POST", "/api/credentials/antigravity", json={
        "id": "ag-rate-limited", "client_id": "cid", "client_secret": "cs", "refresh_token": "rt",
    })

    async def forward(body, cred, stream, client):
        return httpx.Response(
            429,
            json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}},
            headers={"retry-after": "60"},
        )

    app.state.antigravity.forward = forward
    resp = await _request(app, "POST", "/api/credentials/antigravity/ag-rate-limited/test")

    assert resp.status_code == 502
    error = resp.json()["error"]
    assert error["type"] == "upstream_rate_limit"
    assert error["upstream_status"] == 429
    assert error["retry_after"] == 60
    assert "RESOURCE_EXHAUSTED" in error["message"]
    assert "Quota exceeded" in error["message"]


async def test_usage_summary():
    app = _make_admin_app()
    resp = await _request(app, "GET", "/api/usage/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_requests"] == 0
    assert data["total_cost_usd"] == 0
    assert isinstance(data["by_credential"], list)
    assert isinstance(data["by_model"], list)


async def test_web_ui_served():
    app = _make_admin_app()
    resp = await _request(app, "GET", "/")
    assert resp.status_code == 200
    assert "hakimi" in resp.text.lower()
    assert "testCredential" in resp.text
    assert "留空保持当前值" in resp.text
    assert "sidebar" not in resp.text.lower()
    resp2 = await _request(app, "GET", "/ui")
    assert resp2.status_code == 200
