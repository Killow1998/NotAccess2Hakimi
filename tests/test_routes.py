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
    assert data["diagnostics"]["path"] == "state/diagnostics.jsonl"
    assert isinstance(data["diagnostics"]["enabled"], bool)


async def test_readyz_reports_active_local_capacity_without_upstream_traffic():
    app = _make_app_with_state()

    resp = await _request(app, "GET", "/readyz")

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ready",
        "active_credentials": 1,
        "total_credentials": 1,
        "in_flight_requests": 0,
    }


async def test_readyz_returns_503_when_no_credential_is_available():
    app = _make_app_with_state()
    app.state.pool = CredentialPool()

    resp = await _request(app, "GET", "/readyz")

    assert resp.status_code == 503
    assert resp.json() == {
        "status": "not_ready",
        "reason": "no_active_credentials",
        "active_credentials": 0,
        "total_credentials": 0,
        "in_flight_requests": 0,
    }


async def test_readyz_stays_ready_while_active_credential_is_busy():
    app = _make_app_with_state()
    lease = await app.state.pool.acquire(kind="aistudio")
    try:
        resp = await _request(app, "GET", "/readyz")
    finally:
        await app.state.pool.release(lease)

    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
    assert resp.json()["in_flight_requests"] == 1


async def test_readyz_returns_503_when_all_credentials_are_cooling_down():
    app = _make_app_with_state()
    credential = app.state.pool.all_credentials[0]
    app.state.pool.mark_cooldown(credential, retry_after=60)

    resp = await _request(app, "GET", "/readyz")

    assert resp.status_code == 503
    assert resp.json()["reason"] == "no_active_credentials"
    assert resp.json()["total_credentials"] == 1


async def test_authenticated_root_stays_public():
    """The UI root must remain reachable so users can enter the bearer token."""
    app = create_app()
    from hakimi_proxy.auth import BearerAuthMiddleware
    app.user_middleware.clear()
    app.add_middleware(BearerAuthMiddleware, auth_token="secret123")

    resp = await _request(app, "GET", "/")

    assert resp.status_code == 200
    assert 'id="loginView"' in resp.text
    assert "EasyMultiProvider" not in resp.text
    assert "模型与 EMP 集成" not in resp.text
    assert "+ Antigravity 登录" in resp.text
    assert "const localHosts = new Set(['localhost', '127.0.0.1', '::1'])" in resp.text
    assert "凭证迁移" in resp.text
    assert "exportCredentials" in resp.text
    assert "previewCredentialImport" in resp.text
    assert "检查中…" in resp.text
    assert "control_plane" in resp.text


async def test_list_models():
    app = _make_app_with_state()
    resp = await _request(app, "GET", "/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    model_ids = [m["id"] for m in data["data"]]
    assert "gemini-3.7-flash" in model_ids
    tiered = next(m for m in data["data"] if m["id"] == "gemini-3.7-flash-tiered")
    assert tiered["context_window"] == 1_048_576
    assert tiered["max_input_tokens"] == 1_048_576
    assert tiered["output_limit"] == 65_536
    assert tiered["reasoning_levels"] == ["low", "medium", "high"]
    assert tiered["architecture"]["input_modalities"] == ["text", "image"]
    assert tiered["architecture"]["output_modalities"] == ["text"]
    assert tiered["streaming"] is True
    assert "tools" in tiered["supported_parameters"]
    assert "response_format" in tiered["supported_parameters"]
    assert tiered["supported_protocols"] == ["responses", "chat_completions"]
    assert tiered["capability_sources"]["context_window"]["source"] == "observed"


async def test_get_model_returns_catalog_entry_or_404():
    app = _make_app_with_state()
    resp = await _request(app, "GET", "/v1/models/gemini-3.7-flash-tiered")
    assert resp.status_code == 200
    assert resp.json()["context_window"] == 1_048_576

    missing = await _request(app, "GET", "/v1/models/not-a-model")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "not_found_error"


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

    # /readyz is also public, but this empty pool is not ready
    resp = await _request(app, "GET", "/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"

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


async def test_chat_streaming_400_body_is_classified_before_close(monkeypatch):
    app = _make_app_with_state()

    class ErrorStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"error":{"status":"INVALID_ARGUMENT","message":"missing thought signature"}}'

    async def fake_forward(body, cred, stream, client):
        assert stream is True
        return httpx.Response(
            400,
            request=httpx.Request("POST", "https://upstream.test"),
            stream=ErrorStream(),
        )

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    })

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["type"] == "upstream_request_error"
    assert error["upstream_status"] == 400
    assert error["message"] == "INVALID_ARGUMENT: missing thought signature"


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


async def test_chat_upstream_503_is_classified_without_local_500(monkeypatch):
    app = _make_app_with_state()

    async def fake_forward(body, cred, stream, client):
        return httpx.Response(
            503,
            request=httpx.Request("POST", "https://upstream.test"),
            json={"error": {"status": "UNAVAILABLE", "message": "temporarily unavailable"}},
        )

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hello"}],
    })

    assert response.status_code == 503
    assert response.json()["error"] == {
        "type": "upstream_server_error",
        "message": "UNAVAILABLE: temporarily unavailable",
        "upstream_status": 503,
    }
    assert app.state.pool.get_status()[0]["state"] == "cooldown"


async def test_chat_upstream_timeout_is_classified_without_local_500(monkeypatch):
    app = _make_app_with_state()

    async def fake_forward(body, cred, stream, client):
        raise httpx.ConnectTimeout(
            "upstream slow",
            request=httpx.Request("POST", "https://upstream.test"),
        )

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/chat/completions", json={
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hello"}],
    })

    assert response.status_code == 503
    assert response.json()["error"] == {
        "type": "upstream_transport_error",
        "message": "ConnectTimeout: upstream connection failed",
    }
    assert app.state.pool.get_status()[0]["state"] == "cooldown"


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


async def test_chat_stream_client_disconnect_releases_single_flight_lease(monkeypatch):
    app = _make_app_with_state()
    upstream_response = None

    class HangingAfterFirst(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
            await asyncio.Event().wait()

    async def fake_forward(body, cred, stream, client):
        nonlocal upstream_response
        upstream_response = httpx.Response(
            200,
            request=httpx.Request("POST", "https://upstream.test"),
            stream=HangingAfterFirst(),
        )
        return upstream_response

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    body = json.dumps({
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    }).encode()
    request_sent = False
    disconnect = asyncio.Event()
    messages = []

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and b"hello" in message.get("body", b""):
            disconnect.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "root_path": "",
    }

    await asyncio.wait_for(app(scope, receive, send), timeout=1)

    assert any(b"hello" in message.get("body", b"") for message in messages)
    assert upstream_response is not None and upstream_response.is_closed
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
