"""Responses API compatibility tests."""

from pathlib import Path
import tempfile

import httpx
from httpx2 import ASGITransport, AsyncClient

from hakimi_proxy.adapters.aistudio import AIStudioAdapter
from hakimi_proxy.auth import BearerAuthMiddleware
from hakimi_proxy.config import AIStudioCredential, ProxyConfig
from hakimi_proxy.main import create_app
from hakimi_proxy.metering.store import UsageStore
from hakimi_proxy.pool import CredentialPool
from hakimi_proxy.routes.responses import _chat_to_response, responses_to_chat


def _app():
    app = create_app()
    app.user_middleware.clear()
    app.add_middleware(BearerAuthMiddleware, auth_token="")
    pool = CredentialPool(cooldown_seconds=60)
    pool.add_aistudio(AIStudioCredential(id="test-ai", api_key="fake-key"))
    app.state.pool = pool
    app.state.store = UsageStore(Path(tempfile.gettempdir()) / "hakimi_test_responses.db")
    app.state.aistudio = AIStudioAdapter()
    app.state.config = ProxyConfig()
    app.state.max_retries = 1
    return app


async def _request(app, method, path, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def test_responses_request_becomes_chat_request():
    payload = responses_to_chat(
        {
            "model": "antigravity/gemini-3.7-flash-tiered",
            "instructions": "Be concise",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Hello"}],
                }
            ],
            "max_output_tokens": 32,
            "reasoning": {"effort": "low"},
        }
    )

    assert payload == {
        "model": "antigravity/gemini-3.7-flash-tiered",
        "messages": [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Hello"},
        ],
        "stream": False,
        "max_tokens": 32,
        "reasoning_effort": "low",
    }


def test_responses_tool_history_becomes_chat_tool_messages():
    payload = responses_to_chat(
        {
            "model": "antigravity/gemini-3.7-flash-tiered",
            "input": [
                {"type": "message", "role": "user", "content": "Find the file"},
                {
                    "type": "function_call",
                    "call_id": "call-1",
                    "name": "list_files",
                    "arguments": '{"path":"."}',
                    "extra_content": {"google": {"thought_signature": "signature-1"}},
                },
                {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": '{"files":["README.md"]}',
                },
            ],
            "tools": [{
                "type": "function",
                "name": "list_files",
                "description": "List files",
                "parameters": {"type": "object"},
            }],
        }
    )

    assert payload["messages"][1] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "list_files",
                "arguments": '{"path":"."}',
            },
            "extra_content": {"google": {"thought_signature": "signature-1"}},
        }],
    }
    assert payload["messages"][2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"files":["README.md"]}',
    }
    assert payload["tools"] == [{
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files",
            "parameters": {"type": "object"},
        },
    }]


def test_responses_tool_choice_and_json_format_map_to_chat():
    payload = responses_to_chat({
        "model": "gemini-3.7-flash",
        "input": "return json",
        "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
        "tool_choice": {"type": "function", "name": "lookup"},
        "parallel_tool_calls": False,
        "text": {"format": {"type": "json_object"}},
    })

    assert payload["tool_choice"] == {"function": {"name": "lookup"}}
    assert payload["parallel_tool_calls"] is False
    assert payload["response_format"] == {"type": "json_object"}


def test_responses_additional_tools_become_chat_tools():
    payload = responses_to_chat({
        "model": "gemini-3.7-flash",
        "input": [
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [{
                    "type": "namespace",
                    "name": "functions",
                    "tools": [
                        {"type": "custom", "name": "exec", "description": "Run JavaScript"},
                        {"type": "function", "name": "wait", "parameters": {"type": "object"}},
                    ],
                }],
            },
            {"type": "message", "role": "user", "content": "Read README.md"},
        ],
    })

    assert [item["function"]["name"] for item in payload["tools"]] == ["exec", "wait"]
    assert payload["tools"][0]["function"]["parameters"] == {
        "type": "object",
        "properties": {"input": {"type": "string"}},
        "required": ["input"],
        "additionalProperties": False,
    }


def test_responses_custom_tool_history_becomes_chat_tool_messages():
    payload = responses_to_chat({
        "model": "gemini-3.7-flash",
        "input": [
            {"type": "message", "role": "user", "content": "Run it"},
            {
                "type": "custom_tool_call",
                "id": "ctc-1",
                "call_id": "call-1",
                "name": "exec",
                "input": "text('ok')",
                "extra_content": {"google": {"thought_signature": "signature-1"}},
            },
            {
                "type": "custom_tool_call_output",
                "call_id": "call-1",
                "output": [{"type": "input_text", "text": "ok"}],
            },
        ],
    })

    assert payload["messages"][1]["tool_calls"][0]["function"] == {
        "name": "exec",
        "arguments": '{"input":"text(\'ok\')"}',
    }
    assert payload["messages"][1]["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "signature-1"},
    }
    assert payload["messages"][2] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "ok",
    }


def test_responses_reasoning_carrier_binds_to_next_function_call():
    payload = responses_to_chat({
        "model": "gemini-3.7-flash",
        "input": [
            {"type": "message", "role": "user", "content": "Run it"},
            {"type": "reasoning", "encrypted_content": "signature-1", "summary": []},
            {"type": "function_call", "call_id": "call-1", "name": "exec", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call-1", "output": "ok"},
        ],
    })

    assert payload["messages"][1]["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "signature-1"},
    }


def test_responses_reasoning_carrier_after_function_call_binds_back():
    payload = responses_to_chat({
        "model": "gemini-3.7-flash",
        "input": [
            {"type": "message", "role": "user", "content": "Run it"},
            {"type": "function_call", "call_id": "call-1", "name": "exec", "arguments": "{}"},
            {"type": "reasoning", "encrypted_content": "signature-1", "summary": []},
            {"type": "function_call_output", "call_id": "call-1", "output": "ok"},
        ],
    })

    assert payload["messages"][1]["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "signature-1"},
    }


def test_responses_parallel_function_outputs_follow_call_order():
    payload = responses_to_chat({
        "model": "gemini-3.7-flash",
        "input": [
            {"type": "message", "role": "user", "content": "Run both"},
            {"type": "function_call", "call_id": "call-1", "name": "read", "arguments": "{}"},
            {"type": "function_call", "call_id": "call-2", "name": "list", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call-2", "output": "list-result"},
            {"type": "function_call_output", "call_id": "call-1", "output": "read-result"},
        ],
    })

    assert [message["content"] for message in payload["messages"][2:]] == [
        "read-result",
        "list-result",
    ]


def test_responses_input_image_becomes_chat_image_url():
    payload = responses_to_chat({
        "model": "gemini-3.7-flash",
        "input": [{
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Inspect"},
                {"type": "input_image", "image_url": "data:image/png;base64,aGVsbG8="},
            ],
        }],
    })

    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "Inspect"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
    ]


def test_chat_response_becomes_responses_response():
    result = _chat_to_response(
        {
            "id": "chatcmpl-test",
            "model": "antigravity/gemini-3.7-flash-tiered",
            "choices": [{
                "message": {"role": "assistant", "content": "Hello"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        },
        "antigravity/gemini-3.7-flash-tiered",
    )

    assert result["object"] == "response"
    assert result["status"] == "completed"
    assert result["output_text"] == "Hello"
    assert result["output"][0]["content"][0]["text"] == "Hello"
    assert result["usage"] == {
        "input_tokens": 4,
        "output_tokens": 2,
        "total_tokens": 6,
    }


def test_chat_tool_response_becomes_responses_function_call():
    result = _chat_to_response(
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "list_files", "arguments": '{"path":"."}'},
                        "extra_content": {"google": {"thought_signature": "signature-1"}},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        },
        "antigravity/gemini-3.7-flash-tiered",
    )

    assert result["output"][0]["type"] == "reasoning"
    assert result["output"][0]["encrypted_content"] == "signature-1"
    assert result["output"][1] == {
        "id": "call-1",
        "type": "function_call",
        "status": "completed",
        "call_id": "call-1",
        "name": "list_files",
        "arguments": '{"path":"."}',
        "extra_content": {"google": {"thought_signature": "signature-1"}},
    }


def test_chat_custom_tool_response_becomes_responses_custom_tool_call():
    result = _chat_to_response(
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "exec", "arguments": '{"input":"text(\\"ok\\")"}'},
                    "extra_content": {"google": {"thought_signature": "signature-1"}},
                }],
                },
                "finish_reason": "tool_calls",
            }],
        },
        "gemini-3.7-flash",
        custom_tool_names={"exec"},
    )

    assert result["output"][0]["type"] == "reasoning"
    assert result["output"][0]["encrypted_content"] == "signature-1"
    assert result["output"][1] == {
        "id": "call-1",
        "type": "custom_tool_call",
        "status": "completed",
        "call_id": "call-1",
        "name": "exec",
        "input": 'text("ok")',
        "extra_content": {"google": {"thought_signature": "signature-1"}},
    }


async def test_responses_route_translates_non_stream_request(monkeypatch):
    app = _app()
    seen = {}

    async def fake_forward(body, cred, stream, client):
        seen.update(body)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "model": "gemini-3.7-flash",
                "choices": [{"message": {"role": "assistant", "content": "pong"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/responses", json={
        "model": "gemini-3.7-flash",
        "input": "ping",
    })

    assert response.status_code == 200
    assert seen["messages"] == [{"role": "user", "content": "ping"}]
    body = response.json()
    assert body["object"] == "response"
    assert body["output_text"] == "pong"
    assert body["usage"]["total_tokens"] == 2


async def test_responses_route_translates_streaming_text(monkeypatch):
    app = _app()

    class OneChunkStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                b'data: {"choices":[{"delta":{"content":"pong"},'
                b'"finish_reason":"stop"}],"usage":{"prompt_tokens":1,'
                b'"completion_tokens":1,"total_tokens":2}}\n\n'
                b'data: [DONE]\n\n'
            )

    async def fake_forward(body, cred, stream, client):
        assert stream is True
        return httpx.Response(200, request=httpx.Request("POST", "http://upstream"), stream=OneChunkStream())

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/responses", json={
        "model": "gemini-3.7-flash",
        "input": "ping",
        "stream": True,
    })

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: response.created" in response.text
    assert 'event: response.output_text.delta' in response.text
    assert '"delta": "pong"' in response.text
    assert "event: response.completed" in response.text


async def test_responses_route_translates_streaming_tool_call(monkeypatch):
    app = _app()

    class OneChunkStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1",'
                b'"type":"function","function":{"name":"list_files",'
                b'"arguments":"{\\"path\\":\\".\\"}"}}]},'
                b'"finish_reason":"tool_calls"}]}\n\n'
                b'data: [DONE]\n\n'
            )

    async def fake_forward(body, cred, stream, client):
        assert body["tools"][0]["function"]["name"] == "list_files"
        return httpx.Response(200, request=httpx.Request("POST", "http://upstream"), stream=OneChunkStream())

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/responses", json={
        "model": "gemini-3.7-flash",
        "input": "list files",
        "tools": [{"type": "function", "name": "list_files", "parameters": {"type": "object"}}],
        "stream": True,
    })

    assert response.status_code == 200
    assert "event: response.output_item.added" in response.text
    assert "event: response.function_call_arguments.delta" in response.text
    assert "event: response.function_call_arguments.done" in response.text
    assert '"type": "function_call"' in response.text


async def test_responses_route_translates_streaming_custom_tool_call(monkeypatch):
    app = _app()

    class OneChunkStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1",'
                b'"type":"function","function":{"name":"exec",'
                b'"arguments":"{\\"input\\":\\"text(\\\\\\"ok\\\\\\")\\"}"},'
                b'"extra_content":{"google":{"thought_signature":"signature-1"}}}]},'
                b'"finish_reason":"tool_calls"}]}\n\n'
                b'data: [DONE]\n\n'
            )

    async def fake_forward(body, cred, stream, client):
        assert body["tools"][0]["function"]["name"] == "exec"
        return httpx.Response(200, request=httpx.Request("POST", "http://upstream"), stream=OneChunkStream())

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/responses", json={
        "model": "gemini-3.7-flash",
        "input": [
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [{"type": "namespace", "name": "functions", "tools": [
                    {"type": "custom", "name": "exec", "description": "Run JavaScript"},
                ]}],
            },
            {"type": "message", "role": "user", "content": "run"},
        ],
        "stream": True,
    })

    assert response.status_code == 200
    assert "event: response.custom_tool_call_input.delta" in response.text
    assert '"type": "custom_tool_call"' in response.text
    assert '"thought_signature": "signature-1"' in response.text
    assert '"type": "reasoning"' in response.text


async def test_responses_route_emits_detached_reasoning_carrier(monkeypatch):
    app = _app()

    class OneChunkStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                b'data: {"choices":[{"delta":{"na2h_thought_signatures":["signature-1"]}}]}\n\n'
                b'data: [DONE]\n\n'
            )

    async def fake_forward(body, cred, stream, client):
        return httpx.Response(200, request=httpx.Request("POST", "http://upstream"), stream=OneChunkStream())

    monkeypatch.setattr(app.state.aistudio, "forward", fake_forward)
    response = await _request(app, "POST", "/v1/responses", json={
        "model": "gemini-3.7-flash",
        "input": "run",
        "stream": True,
    })

    assert response.status_code == 200
    assert '"type": "reasoning"' in response.text
    assert '"encrypted_content": "signature-1"' in response.text


async def test_responses_stream_surfaces_post_first_event_error(monkeypatch):
    app = _app()

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
    response = await _request(app, "POST", "/v1/responses", json={
        "model": "gemini-3.7-flash",
        "input": "hello",
        "stream": True,
    })

    assert response.status_code == 200
    assert '"type": "error"' in response.text
    assert "Upstream stream failed after output started" in response.text
    assert '"type": "response.completed"' not in response.text
