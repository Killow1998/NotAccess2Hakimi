"""Tests for adapter request/response transformations."""

import json
import time
import asyncio

import httpx
import pytest

from hakimi_proxy.adapters.aistudio import AIStudioAdapter
from hakimi_proxy.adapters import antigravity as antigravity_module
from hakimi_proxy.adapters.antigravity import (
    LOAD_CODE_ASSIST_URL,
    ONBOARD_USER_URL,
    AntigravityAdapter,
    _gemini_chunk_to_openai_chunk,
    _gemini_to_openai,
    _openai_to_gemini,
    _resolve_model_name,
)
from hakimi_proxy.config import AIStudioCredential, AntigravityCredential
from hakimi_proxy.pool import PooledCredential
from hakimi_proxy.routes.chat import _select_adapter, _stream_response


def _make_ai_cred() -> PooledCredential:
    return PooledCredential(credential=AIStudioCredential(id="test", api_key="AIzaSy-test"))


def _make_ag_cred() -> PooledCredential:
    return PooledCredential(
        credential=AntigravityCredential(
            id="test", client_id="cid", client_secret="cs", refresh_token="rt"
        )
    )


# --- AI Studio adapter ---

def test_aistudio_supports_model():
    adapter = AIStudioAdapter()
    assert adapter.supports_model("gemini-3.7-flash")
    assert adapter.supports_model("gemini-2.0-flash")
    assert not adapter.supports_model("gpt-4")


def test_aistudio_extract_usage():
    adapter = AIStudioAdapter()
    body = {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
    usage = adapter.extract_usage(body)
    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 50


def test_aistudio_transform_stream_line_passthrough():
    adapter = AIStudioAdapter()
    chunk = {"choices": [{"delta": {"content": "hello"}}]}
    line = f"data: {json.dumps(chunk)}"
    transformed, usage = adapter.transform_stream_line(line)
    assert transformed == json.dumps(chunk)
    assert usage is None


def test_aistudio_transform_stream_line_with_usage():
    adapter = AIStudioAdapter()
    chunk = {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    line = f"data: {json.dumps(chunk)}"
    transformed, usage = adapter.transform_stream_line(line)
    assert transformed == json.dumps(chunk)
    assert usage is not None
    assert usage["prompt_tokens"] == 10


def test_aistudio_transform_stream_done():
    adapter = AIStudioAdapter()
    transformed, usage = adapter.transform_stream_line("data: [DONE]")
    assert transformed is None
    assert usage is None


def test_aistudio_transform_non_data_line():
    adapter = AIStudioAdapter()
    transformed, usage = adapter.transform_stream_line(": comment")
    assert transformed is None
    assert usage is None


# --- Antigravity adapter ---

def test_antigravity_supports_model():
    adapter = AntigravityAdapter()
    assert adapter.supports_model("gemini-3.7-flash")
    assert adapter.supports_model("gemini-3.7-flash-tiered")
    assert adapter.supports_model("gemini-3.6-flash-high")
    assert adapter.supports_model("gemini-3.6-flash-medium")
    assert adapter.supports_model("gemini-2.5-pro")
    assert not adapter.supports_model("gemini-3.7-flash-high")
    assert not adapter.supports_model("gpt-4")


def test_antigravity_uses_catalog_confirmed_model_alias():
    assert _resolve_model_name("gemini-3.7-flash") == "gemini-3.7-flash-tiered"
    assert _resolve_model_name("gemini-3.7-flash-tiered") == "gemini-3.7-flash-tiered"
    assert _resolve_model_name("gemini-3.7-flash-high") == "gemini-3.7-flash-high"


def test_provider_prefix_selects_antigravity():
    aistudio = AIStudioAdapter()
    antigravity = AntigravityAdapter()

    assert _select_adapter("antigravity/gemini-3.7-flash", aistudio, antigravity) is antigravity
    assert _select_adapter("gemini-3.7-flash", aistudio, antigravity) is aistudio


def test_openai_to_gemini_basic():
    """System message goes to systemInstruction; user/assistant to contents."""
    body = {
        "model": "gemini-3.7-flash",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
        ],
    }
    result = _openai_to_gemini(body)
    assert "systemInstruction" in result
    assert result["systemInstruction"]["parts"][0]["text"] == "You are helpful."
    assert len(result["contents"]) == 3
    assert result["contents"][0]["role"] == "user"
    assert result["contents"][1]["role"] == "model"
    assert result["contents"][2]["role"] == "user"


def test_openai_to_gemini_with_gen_config():
    """Generation config fields are mapped."""
    body = {
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.7,
        "max_tokens": 100,
        "top_p": 0.9,
    }
    result = _openai_to_gemini(body)
    gc = result["generationConfig"]
    assert gc["temperature"] == 0.7
    assert gc["maxOutputTokens"] == 100
    assert gc["topP"] == 0.9


def test_openai_to_gemini_no_system():
    """Without system message, systemInstruction is absent."""
    body = {
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "hi"}],
    }
    result = _openai_to_gemini(body)
    assert "systemInstruction" not in result
    assert len(result["contents"]) == 1


def test_openai_to_gemini_tools_multimodal_and_signatures():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "inspect_image", "arguments": "{\"detail\":true}"},
                    "extra_content": {"google": {"thought_signature": "signature-1"}},
                }],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "{\"status\":\"ok\"}"},
        ],
        "tools": [{
            "type": "function",
            "function": {
                "name": "inspect_image",
                "description": "Inspect an image",
                "parameters": {"type": "object", "properties": {"detail": {"type": "boolean"}}},
            },
        }],
        "tool_choice": "required",
        "reasoning_effort": "low",
    }

    result = _openai_to_gemini(body)

    assert result["contents"][0]["parts"][1] == {
        "inlineData": {"mimeType": "image/png", "data": "aGVsbG8="}
    }
    call_part = result["contents"][1]["parts"][0]
    assert call_part["functionCall"] == {
        "name": "inspect_image",
        "args": {"detail": True},
        "id": "call-1",
    }
    assert call_part["thoughtSignature"] == "signature-1"
    assert result["contents"][2]["parts"][0]["functionResponse"] == {
        "name": "inspect_image", "response": {"status": "ok"}, "id": "call-1"
    }
    assert result["tools"][0]["functionDeclarations"][0]["parametersJsonSchema"]["type"] == "object"
    assert result["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
    assert result["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


def test_gemini_to_openai_basic():
    """Gemini response converts to OpenAI format."""
    gemini_body = {
        "candidates": [
            {
                "content": {"parts": [{"text": "Hello!"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "totalTokenCount": 15,
        },
    }
    result = _gemini_to_openai(gemini_body, "gemini-3.7-flash")
    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["content"] == "Hello!"
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["usage"]["prompt_tokens"] == 10
    assert result["usage"]["completion_tokens"] == 5
    assert result["model"] == "gemini-3.7-flash"


def test_gemini_to_openai_max_tokens():
    """finishReason MAX_TOKENS maps to 'length'."""
    gemini_body = {
        "candidates": [
            {"content": {"parts": [{"text": "..."}]}, "finishReason": "MAX_TOKENS"}
        ],
        "usageMetadata": {},
    }
    result = _gemini_to_openai(gemini_body, "gemini-3.7-flash")
    assert result["choices"][0]["finish_reason"] == "length"


def test_gemini_to_openai_tool_call_preserves_signature():
    result = _gemini_to_openai({
        "response": {
            "candidates": [{
                "content": {"parts": [{
                    "functionCall": {"name": "get_weather", "args": {"city": "Paris"}},
                    "thoughtSignature": "signature-1",
                }]},
                "finishReason": "STOP",
            }],
            "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 3},
        }
    }, "gemini-3.7-flash")

    choice = result["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] is None
    call = choice["message"]["tool_calls"][0]
    assert call["function"]["arguments"] == '{"city":"Paris"}'
    assert call["extra_content"]["google"]["thought_signature"] == "signature-1"


def test_gemini_to_openai_preserves_detached_signature_carrier():
    result = _gemini_to_openai({
        "response": {
            "candidates": [{
                "content": {"parts": [{"text": "thinking", "thought": True, "thoughtSignature": "signature-1"}]},
                "finishReason": "STOP",
            }],
        }
    }, "gemini-3.7-flash")

    message = result["choices"][0]["message"]
    assert message["na2h_thought_signatures"] == ["signature-1"]


def test_antigravity_stream_preserves_detached_signature_carrier():
    transformed, _ = _gemini_chunk_to_openai_chunk({
        "response": {"candidates": [{"content": {"parts": [
            {"text": "thinking", "thought": True, "thoughtSignature": "signature-1"},
        ]}}]},
    }, "gemini-3.7-flash", "chunk-1")

    delta = json.loads(transformed)["choices"][0]["delta"]
    assert delta["na2h_thought_signatures"] == ["signature-1"]


def test_antigravity_transform_stream_line():
    """Cloud Code SSE data line transforms to OpenAI SSE chunk."""
    adapter = AntigravityAdapter()
    gemini_data = {
        "response": {
            "candidates": [{"content": {"parts": [{"text": "Hello"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2},
        }
    }
    line = f"data: {json.dumps(gemini_data)}"
    transformed, usage = adapter.transform_stream_line(line)
    assert transformed is not None
    chunk = json.loads(transformed)
    assert chunk["object"] == "chat.completion.chunk"
    assert chunk["choices"][0]["delta"]["content"] == "Hello"
    assert usage is not None
    assert usage["prompt_tokens"] == 10


def test_antigravity_transform_stream_tool_call():
    adapter = AntigravityAdapter()
    line = "data: " + json.dumps({"response": {"candidates": [{
        "content": {"parts": [{
            "functionCall": {"name": "get_weather", "args": {"city": "Paris"}},
            "thoughtSignature": "signature-1",
        }]},
        "finishReason": "STOP",
    }]}})

    transformed, _ = adapter.transform_stream_line(line)

    chunk = json.loads(transformed)
    choice = chunk["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["delta"]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert choice["delta"]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "signature-1"


def test_antigravity_extract_usage():
    adapter = AntigravityAdapter()
    body = {
        "response": {
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": 50,
                "totalTokenCount": 150,
            }
        }
    }
    usage = adapter.extract_usage(body)
    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 50
    assert usage["total_tokens"] == 150


@pytest.mark.asyncio
async def test_antigravity_refresh_rotates_token_once_for_concurrent_requests(monkeypatch):
    calls = 0
    updates = []

    class Response:
        status_code = 200

        def json(self):
            return {"access_token": "new-access", "refresh_token": "rotated-refresh", "expires_in": 3600}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return Response()

    monkeypatch.setattr(antigravity_module.httpx, "AsyncClient", lambda **kwargs: Client())
    pooled = _make_ag_cred()
    adapter = AntigravityAdapter(on_credential_update=lambda: updates.append(True))

    await asyncio.gather(adapter.refresh_credential(pooled), adapter.refresh_credential(pooled))

    assert calls == 1
    assert updates == [True]
    assert pooled.credential.access_token == "new-access"
    assert pooled.credential.refresh_token == "rotated-refresh"


@pytest.mark.asyncio
async def test_antigravity_discovers_project_before_forwarding():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url) == LOAD_CODE_ASSIST_URL:
            return httpx.Response(200, json={"cloudaicompanionProject": {"id": "dynamic-project"}})
        payload = json.loads(request.content)
        assert payload["project"] == "dynamic-project"
        return httpx.Response(200, json={"response": {"candidates": []}})

    cred = _make_ag_cred()
    cred.credential.access_token = "token"
    cred.credential.expires_at = time.time() + 3600
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await AntigravityAdapter().forward(
            {"model": "gemini-3.7-flash", "messages": [{"role": "user", "content": "hi"}]},
            cred,
            False,
            client,
        )

    assert response.status_code == 200
    assert cred.credential.project == "dynamic-project"
    assert json.loads(requests[-1].content)["model"] == "gemini-3.7-flash-tiered"
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_antigravity_falls_back_when_daily_endpoint_returns_404(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "hakimi_proxy.adapters.antigravity.ENDPOINTS",
        ["https://daily.test", "https://prod.test"],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "daily.test":
            return httpx.Response(404, request=request)
        return httpx.Response(200, request=request, json={"response": {"candidates": []}})

    cred = _make_ag_cred()
    cred.credential.access_token = "token"
    cred.credential.expires_at = time.time() + 3600
    cred.credential.project = "project-1"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await AntigravityAdapter().forward(
            {"model": "gemini-3.7-flash", "messages": [{"role": "user", "content": "hi"}]},
            cred,
            False,
            client,
        )

    assert response.status_code == 200
    assert calls == ["daily.test", "prod.test"]


@pytest.mark.asyncio
async def test_antigravity_stream_response_is_not_buffered():
    class OneChunkStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"response":{"candidates":[]}}\n\n'

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=OneChunkStream())

    cred = _make_ag_cred()
    cred.credential.access_token = "token"
    cred.credential.expires_at = time.time() + 3600
    cred.credential.project = "project-1"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await AntigravityAdapter().forward(
            {"model": "antigravity/gemini-3.7-flash", "messages": [{"role": "user", "content": "hi"}]},
            cred,
            True,
            client,
        )
        assert response.is_stream_consumed is False
        await response.aclose()


@pytest.mark.asyncio
async def test_antigravity_onboarding_requires_opt_in():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"allowedTiers": [{"id": "free-tier", "isDefault": True}]})

    cred = _make_ag_cred()
    cred.credential.access_token = "token"
    cred.credential.expires_at = time.time() + 3600
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="enable auto_onboard"):
            await AntigravityAdapter().forward(
                {"model": "gemini-3.7-flash", "messages": [{"role": "user", "content": "hi"}]},
                cred,
                False,
                client,
            )


@pytest.mark.asyncio
async def test_antigravity_onboards_when_explicitly_enabled(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == LOAD_CODE_ASSIST_URL:
            return httpx.Response(200, json={"allowedTiers": [{"id": "tier-1", "isDefault": True}]})
        if str(request.url) == ONBOARD_USER_URL:
            return httpx.Response(200, json={
                "done": True,
                "response": {"cloudaicompanionProject": "onboarded-project"},
            })
        payload = json.loads(request.content)
        assert payload["project"] == "onboarded-project"
        return httpx.Response(200, json={"response": {"candidates": []}})

    monkeypatch.setattr("hakimi_proxy.adapters.antigravity.ONBOARD_POLL_SECONDS", 0)
    cred = _make_ag_cred()
    cred.credential.access_token = "token"
    cred.credential.expires_at = time.time() + 3600
    cred.credential.auto_onboard = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await AntigravityAdapter().forward(
            {"model": "gemini-3.7-flash", "messages": [{"role": "user", "content": "hi"}]},
            cred,
            False,
            client,
        )

    assert response.status_code == 200
    assert calls[:2] == [LOAD_CODE_ASSIST_URL, ONBOARD_USER_URL]


@pytest.mark.asyncio
async def test_antigravity_stream_keeps_tool_finish_reason():
    upstream = {
        "response": {
            "candidates": [{
                "content": {"parts": [{"functionCall": {"name": "get_weather", "args": {}}}]},
                "finishReason": "STOP",
            }]
        }
    }
    request = httpx.Request("POST", "https://example.test")
    response = httpx.Response(200, request=request, content=f"data: {json.dumps(upstream)}\n\n")
    client = httpx.AsyncClient()
    stream = _stream_response(
        response,
        AntigravityAdapter(),
        _make_ag_cred(),
        "gemini-3.7-flash",
        object(),
        client,
    )

    chunks = [chunk async for chunk in stream.body_iterator]
    body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)

    assert body.count('"finish_reason": "tool_calls"') == 1
    assert '"finish_reason": "stop"' not in body
    assert body.endswith("data: [DONE]\n\n")
