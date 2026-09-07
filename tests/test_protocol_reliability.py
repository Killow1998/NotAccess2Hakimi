"""Failure injection for lease ownership and protocol terminal states."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest
import httpx
from fastapi.responses import StreamingResponse

from hakimi_proxy.adapters.aistudio import AIStudioAdapter
from hakimi_proxy.adapters.antigravity import AntigravityAdapter, _finish_reason, _gemini_chunk_to_openai_chunk
from hakimi_proxy.config import AIStudioCredential
from hakimi_proxy.pool import CredentialPool, CredentialUnavailable
from hakimi_proxy.routes.chat import _cleanup, _stream_response, _acquire_for_request, _run_chat_completion, _prepare_stream
from hakimi_proxy.routes.responses import _chat_to_response, _response_stream, _run_responses, responses_to_chat


def chunk(delta, reason=None, usage=None):
    value = {"choices": [{"delta": delta, "finish_reason": reason}]}
    if usage:
        value["usage"] = usage
    return "data: " + json.dumps(value) + "\n\n"


async def events(response):
    result = []
    async for raw in response.body_iterator:
        raw = raw.decode() if isinstance(raw, bytes) else raw
        for line in raw.splitlines():
            if line.startswith("data: ") and line != "data: [DONE]":
                result.append(json.loads(line[6:]))
    return result


@pytest.mark.parametrize("reason,status", [
    ("stop", "completed"), ("tool_calls", "completed"),
    ("length", "incomplete"), ("content_filter", "incomplete"),
    (None, "failed"), ("unknown", "failed"),
])
async def test_terminal_states_preserve_partial_tools(reason, status):
    arguments = '{"path":"file"}' if status == "completed" else '{"path":'
    call = {"index": 0, "id": "call_1", "function": {"name": "read", "arguments": arguments}}
    async def source():
        yield chunk({"tool_calls": [call]}, reason)
    output = await events(_response_stream(StreamingResponse(source()), "test"))
    terminal = output[-1]
    assert terminal["type"] == "response." + status
    response = terminal["response"]
    assert response["status"] == status
    assert response["output"][0]["arguments"] == arguments
    if status != "completed":
        assert not any(e["type"] == "response.function_call_arguments.done" for e in output)
        assert response["output"][0]["status"] == "incomplete"
    converted = _chat_to_response({"choices": [{
        "message": {"tool_calls": [call]}, "finish_reason": reason,
    }]}, "test")
    assert converted["status"] == status


@pytest.mark.parametrize("reason,expected", [(None, None), ("STOP", "tool_calls"),
    ("MAX_TOKENS", "length"), ("SAFETY", "content_filter")])
def test_gemini_tool_activity_is_not_terminal_evidence(reason, expected):
    assert _finish_reason(reason, True) == expected


@pytest.mark.parametrize("close_fails", [False, True])
async def test_metering_and_close_errors_cannot_leak_stream_lease(close_fails):
    pool = CredentialPool()
    pool.add_aistudio(AIStudioCredential(id="test", api_key="fake"))
    cred = await pool.acquire()
    closed = []
    class Resource:
        async def aclose(self):
            closed.append(self)
            if close_fails:
                raise OSError("injected close error")
    class Store:
        def record(self, value):
            raise sqlite3.OperationalError("injected disk error")
    async def source():
        yield chunk({"content": "ok"}, "stop", {"prompt_tokens": 1, "completion_tokens": 1})
    resp, client = Resource(), Resource()
    output = await events(_stream_response(resp, AIStudioAdapter(), cred, "test", Store(), client,
        stream_iter=source(), pool=pool))
    assert not any("error" in event for event in output)
    assert closed == [resp, client]
    assert cred.in_flight == 0
    next_lease = await pool.acquire(timeout_seconds=0)
    await pool.release(next_lease)


async def test_cleanup_finishes_when_caller_is_cancelled():
    pool = CredentialPool()
    pool.add_aistudio(AIStudioCredential(id="test", api_key="fake"))
    cred = await pool.acquire()
    started, resume = asyncio.Event(), asyncio.Event()
    class Resource:
        async def aclose(self):
            started.set()
            await resume.wait()
    task = asyncio.create_task(_cleanup(Resource(), None, pool, cred))
    await started.wait()
    task.cancel()
    resume.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cred.in_flight == 0


async def test_bare_eof_does_not_emit_stop_or_success():
    pool = CredentialPool()
    pool.add_aistudio(AIStudioCredential(id="test", api_key="fake"))
    cred = await pool.acquire()
    class Resource:
        async def aclose(self):
            pass
    async def source():
        yield chunk({"content": "partial"})
    output = await events(_stream_response(Resource(), AIStudioAdapter(), cred, "test", None, Resource(),
        stream_iter=source(), pool=pool))
    assert any("error" in event for event in output)
    assert not any(c.get("finish_reason") == "stop" for e in output for c in e.get("choices", []))
    assert cred.last_success_at == 0
    assert cred.in_flight == 0


async def test_busy_providers_share_one_deadline(monkeypatch):
    from hakimi_proxy.routes import chat
    clock = [0.0]
    monkeypatch.setattr(chat.time, "monotonic", lambda: clock[0])
    waits = []
    class BusyPool:
        async def acquire(self, *, kind, timeout_seconds):
            waits.append(timeout_seconds)
            clock[0] += timeout_seconds
            raise CredentialUnavailable("busy_timeout")
    ai, ag = AIStudioAdapter(), AntigravityAdapter()
    with pytest.raises(CredentialUnavailable):
        await _acquire_for_request(BusyPool(), ai, ai, ag, "gemini-3.8-flash", 10)
    assert sum(waits) == 10


async def test_namespace_collisions_fail_before_upstream():
    body = {"input": "hello", "tools": [
        {"type": "namespace", "name": name, "tools": [{"type": "function", "name": "read"}]}
        for name in ("files", "database")
    ]}
    result = await _run_responses(SimpleNamespace(), body)
    assert result.status_code == 400
    assert json.loads(result.body)["error"]["type"] == "invalid_request_error"


async def test_parallel_signatures_survive_two_tool_round_trips():
    history = []
    for step in range(2):
        calls = [{"id": f"call_{step}_{i}", "function": {"name": "read", "arguments": "{}"},
            "extra_content": {"google": {"thought_signature": f" opaque-{step}-{i} "}}}
            for i in range(2)]
        converted = _chat_to_response({"choices": [{"message": {"tool_calls": calls},
            "finish_reason": "tool_calls"}]}, "test")
        history.extend(converted["output"])
        history.extend({"type": "function_call_output", "call_id": c["id"], "output": "ok"}
            for c in reversed(calls))
    messages = responses_to_chat({"input": history})["messages"]
    assistants = [m for m in messages if m["role"] == "assistant"]
    assert len(assistants) == 2
    for step, message in enumerate(assistants):
        assert [c["extra_content"]["google"]["thought_signature"] for c in message["tool_calls"]] == [
            f" opaque-{step}-{i} " for i in range(2)]


async def test_empty_tail_signature_is_preserved_in_stream_and_history():
    signature = " opaque-tail "
    async def source():
        for candidate in [
            {"content": {"parts": [{"text": "ok"}]}},
            {"content": {"parts": [{"text": "", "thoughtSignature": signature}]}, "finishReason": "STOP"},
        ]:
            converted, _ = _gemini_chunk_to_openai_chunk({"candidates": [candidate]}, "test", "chunk")
            yield "data: " + converted + "\n\n"
    output = await events(_response_stream(StreamingResponse(source()), "test"))
    final = output[-1]["response"]
    assert final["status"] == "completed"
    reasoning = [item for item in final["output"] if item["type"] == "reasoning"]
    assert reasoning[0]["encrypted_content"] == signature
    payload = responses_to_chat({"input": reasoning + [{"type": "function_call", "name": "read",
        "call_id": "call", "arguments": "{}"}]})
    assert payload["messages"][0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == signature


async def test_cleanup_releases_lease_when_resource_close_is_cancelled():
    pool = CredentialPool()
    pool.add_aistudio(AIStudioCredential(id="test", api_key="fake"))
    cred = await pool.acquire()
    closed = []
    class Response:
        async def aclose(self):
            raise asyncio.CancelledError()
    class Client:
        async def aclose(self):
            closed.append(True)
    with pytest.raises(asyncio.CancelledError):
        await _cleanup(Response(), Client(), pool, cred)
    assert closed == [True]
    assert cred.in_flight == 0


async def test_nonstream_metering_failure_does_not_replay_completed_request():
    pool = CredentialPool()
    pool.add_aistudio(AIStudioCredential(id="test", api_key="fake"))
    calls = []
    class Adapter(AIStudioAdapter):
        async def forward(self, *args):
            calls.append(True)
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"},
                "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    class Store:
        def record(self, value):
            raise sqlite3.OperationalError("injected")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool, store=Store(),
        aistudio=Adapter(), antigravity=AntigravityAdapter(), max_retries=3,
        config=SimpleNamespace(proxy=""), upstream_client_factory=lambda _: httpx.AsyncClient())))
    result = await _run_chat_completion(request, {"model": "gemini-3.8-flash"})
    assert result.status_code == 200
    assert len(calls) == 1
    assert pool.all_credentials[0].in_flight == 0


@pytest.mark.parametrize("reason", ["length", "content_filter"])
async def test_empty_truncated_output_survives_prefetch(reason):
    resp = httpx.Response(200, text=chunk({}, reason))
    source, prefetched = await _prepare_stream(resp, AIStudioAdapter())
    assert prefetched
    assert [line async for line in source] == [""]


async def test_transport_exception_keeps_partial_arguments_without_finalizing():
    async def source():
        yield chunk({"tool_calls": [{"index": 0, "id": "call", "function": {
            "name": "read", "arguments": '{"path":'}}]})
        raise OSError("injected")
    output = await events(_response_stream(StreamingResponse(source()), "test"))
    failed = next(e["response"] for e in output if e["type"] == "response.failed")
    assert failed["output"][0]["arguments"] == '{"path":'
    assert not any(e["type"] == "response.function_call_arguments.done" for e in output)


async def test_repeated_cancellation_still_closes_and_releases():
    from hakimi_proxy.routes.chat import _cleanup
    from hakimi_proxy.config import AIStudioCredential
    from hakimi_proxy.pool import CredentialPool

    pool = CredentialPool()
    pool.add_aistudio(AIStudioCredential("one", "synthetic-key"))
    credential = await pool.acquire(timeout_seconds=0)
    closing = asyncio.Event()
    allow_close = asyncio.Event()

    class Resource:
        closed = False

        async def aclose(self):
            closing.set()
            await allow_close.wait()
            self.closed = True

    resource = Resource()
    cleanup = asyncio.create_task(_cleanup(resource, None, pool, credential))
    await closing.wait()
    cleanup.cancel()
    await asyncio.sleep(0)
    cleanup.cancel()
    await asyncio.sleep(0)
    allow_close.set()
    with pytest.raises(asyncio.CancelledError):
        await cleanup
    assert resource.closed
    assert credential.in_flight == 0
    assert await pool.acquire(timeout_seconds=0) is credential
    await pool.release(credential)


@pytest.mark.parametrize("custom", [False, True])
async def test_late_tool_identity_has_consistent_added_and_done(custom):
    arguments = '{"input":"hello"}' if custom else '{"path":"file"}'
    async def source():
        yield chunk({"tool_calls": [{"index": 0, "function": {"arguments": arguments[:6]}}]})
        yield chunk({"tool_calls": [{"index": 0, "id": "call_late"}]})
        yield chunk({"tool_calls": [{"index": 0, "function": {"name": "run", "arguments": arguments[6:]}}]}, "tool_calls")
    output = await events(_response_stream(StreamingResponse(source()), "test", {"run"} if custom else set()))
    added = next(e["item"] for e in output if e["type"] == "response.output_item.added")
    done = next(e["item"] for e in output if e["type"] == "response.output_item.done")
    assert added["type"] == done["type"] == ("custom_tool_call" if custom else "function_call")
    assert added["id"] == done["id"]
    assert added["name"] == done["name"] == "run"
    assert output[-1]["type"] == "response.completed"
    assert done["input" if custom else "arguments"] == ("hello" if custom else arguments)


@pytest.mark.parametrize("arguments", ['{"path":', '[]', 'null'])
async def test_finished_but_invalid_tool_json_does_not_complete(arguments):
    call = {"index": 0, "id": "call_bad", "function": {"name": "run", "arguments": arguments}}
    async def source():
        yield chunk({"tool_calls": [call]}, "tool_calls")
    output = await events(_response_stream(StreamingResponse(source()), "test"))
    assert output[-1]["type"] == "response.failed"
    assert not any(e["type"].endswith(".done") for e in output)
    converted = _chat_to_response({"choices": [{"message": {"tool_calls": [call]}, "finish_reason": "tool_calls"}]}, "test")
    assert converted["status"] == "failed"


async def test_missing_tool_name_does_not_publish_wrong_item_type():
    async def source():
        yield chunk({"tool_calls": [{"index": 0, "id": "call_missing", "function": {"arguments": '{}'}}]}, "tool_calls")
    output = await events(_response_stream(StreamingResponse(source()), "test"))
    assert output[-1]["type"] == "response.failed"
    assert not any(e["type"] == "response.output_item.added" for e in output)
