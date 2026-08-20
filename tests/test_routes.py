"""Integration tests for API routes using FastAPI TestClient."""

import asyncio
import json
import tempfile
from pathlib import Path

import httpx
from httpx2 import ASGITransport, AsyncClient

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


async def _request(app, method, path, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


async def test_healthz():
    app = _make_app_with_state()
    resp = await _request(app, "GET", "/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["total_credentials"] == 1
    assert data["in_flight_requests"] == 0
    assert data["proxy_source"] in {"config", "environment", "system", "direct"}


async def test_authenticated_root_stays_public():
    """The UI root must remain reachable so users can enter the bearer token."""
    app = create_app()
    from hakimi_proxy.auth import BearerAuthMiddleware
    app.user_middleware.clear()
    app.add_middleware(BearerAuthMiddleware, auth_token="secret123")

    resp = await _request(app, "GET", "/")

    assert resp.status_code == 200
    assert 'id="loginView"' in resp.text


async def test_list_models():
    app = _make_app_with_state()
    resp = await _request(app, "GET", "/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    model_ids = [m["id"] for m in data["data"]]
    assert "gemini-3.7-flash" in model_ids


async def test_credentials_status():
    app = _make_app_with_state()
    resp = await _request(app, "GET", "/v1/credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["credentials"]) == 1
    assert data["credentials"][0]["id"] == "test-ai"
    assert data["credentials"][0]["state"] == "active"


async def test_usage_empty():
    app = _make_app_with_state()
    resp = await _request(app, "GET", "/v1/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total_requests"] == 0
    assert data["records"] == []


async def test_auth_rejects_no_token():
    """When auth_token is set, requests without Bearer are rejected."""
    app = create_app()
    # Manually set auth token by recreating middleware
    from hakimi_proxy.auth import BearerAuthMiddleware
    app.user_middleware.clear()
    app.add_middleware(BearerAuthMiddleware, auth_token="secret123")
    app.state.pool = CredentialPool()
    # /healthz is public
    resp = await _request(app, "GET", "/healthz")
    assert resp.status_code == 200

    # /v1/models requires auth
    resp = await _request(app, "GET", "/v1/models")
    assert resp.status_code == 401

    # With correct token
    resp = await _request(app, "GET", "/v1/models", headers={"Authorization": "Bearer secret123"})
    assert resp.status_code == 200


async def test_chat_no_credentials_returns_503():
    """With no available credentials, returns 503."""
    app = create_app()
    from hakimi_proxy.auth import BearerAuthMiddleware
    app.user_middleware.clear()
    app.add_middleware(BearerAuthMiddleware, auth_token="")
    app.state.pool = CredentialPool()
    app.state.config = ProxyConfig()
    resp = await _request(app, "POST", "/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert resp.status_code == 503
    assert "exhausted" in resp.json()["error"]["message"]


async def test_chat_stream_retries_before_first_upstream_event(monkeypatch):
    app = _make_app_with_state()
    app.state.pool.add_aistudio(AIStudioCredential(id="second-ai", api_key="fake-key-2"))
    calls = []

    class FailingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise RuntimeError("connection reset before first event")
            yield b""

    class GoodStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n\n'

    async def fake_forward(body, cred, stream, client):
        calls.append(cred.id)
        request = httpx.Request("POST", "https://upstream.test")
        source = FailingStream() if len(calls) == 1 else GoodStream()
        return httpx.Response(200, request=request, stream=source)

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    })

    assert response.status_code == 200
    assert calls == ["test-ai", "second-ai"]
    assert "hello" in response.text


async def test_chat_stream_normalizes_failure_after_first_event(monkeypatch):
    app = _make_app_with_state()

    class FailingAfterFirst(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
            raise RuntimeError("connection reset after first event")

    async def fake_forward(body, cred, stream, client):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://upstream.test"),
            stream=FailingAfterFirst(),
        )

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    })

    assert response.status_code == 200
    assert "hello" in response.text
    assert "Upstream stream failed after output started" in response.text


async def test_chat_terminal_400_is_not_retried(monkeypatch):
    app = _make_app_with_state()
    calls = 0

    async def fake_forward(body, cred, stream, client):
        nonlocal calls
        calls += 1
        return httpx.Response(
            400,
            request=httpx.Request("POST", "https://upstream.test"),
            json={"error": {"status": "INVALID_ARGUMENT", "message": "bad request"}},
        )

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hello"}],
    })

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "upstream_request_error"
    assert calls == 1


async def test_chat_429_fails_over_to_another_credential(monkeypatch):
    app = _make_app_with_state()
    app.state.pool.add_aistudio(AIStudioCredential(id="second-ai", api_key="fake-key-2"))
    calls = []

    async def fake_forward(body, cred, stream, client):
        calls.append(cred.id)
        if len(calls) == 1:
            return httpx.Response(
                429,
                request=httpx.Request("POST", "https://upstream.test"),
                headers={"retry-after": "60"},
                json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "rate limited"}},
            )
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://upstream.test"),
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]},
        )

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hello"}],
    })

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok"
    assert calls == ["test-ai", "second-ai"]


async def test_chat_empty_success_is_rejected(monkeypatch):
    app = _make_app_with_state()

    async def fake_forward(body, cred, stream, client):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://upstream.test"),
            json={"choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}]},
        )

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hello"}],
    })

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "empty_upstream_response"


async def test_chat_invalid_json_is_reported_as_upstream_error(monkeypatch):
    app = _make_app_with_state()

    async def fake_forward(body, cred, stream, client):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://upstream.test"),
            content=b"not-json",
        )

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hello"}],
    })

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "upstream_invalid_response"


async def test_chat_stream_releases_single_flight_lease(monkeypatch):
    app = _make_app_with_state()

    class GoodStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'

    async def fake_forward(body, cred, stream, client):
        return httpx.Response(200, request=httpx.Request("POST", "https://upstream.test"), stream=GoodStream())

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    })

    assert response.status_code == 200
    assert "ok" in response.text
    assert app.state.pool.get_status()[0]["in_flight"] == 0


async def test_eight_concurrent_requests_are_single_flight_per_credential(monkeypatch):
    app = _make_app_with_state()
    active = 0
    max_active = 0

    async def fake_forward(body, cred, stream, client):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://upstream.test"),
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]},
        )

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    responses = await asyncio.gather(*[
        _request(app, "POST", "/v1/chat/completions", json={
            "model": "gemini-3.7-flash",
            "messages": [{"role": "user", "content": "hello"}],
        })
        for _ in range(8)
    ])

    assert [response.status_code for response in responses] == [200] * 8
    assert max_active == 1
    assert app.state.pool.get_status()[0]["in_flight"] == 0
