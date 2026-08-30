"""Unified verification report safety and orchestration tests."""

import json

import httpx
import pytest
from fastapi.responses import JSONResponse, StreamingResponse

from hakimi_proxy.config import AntigravityCredential
from hakimi_proxy.errors import UpstreamError, UpstreamFailure
from hakimi_proxy.pool import CredentialPool
from hakimi_proxy.verification import (
    fingerprint_response,
    replay_verification_report,
    run_full_verification,
)


def _completed_response(*output, output_text="", status="completed"):
    return {
        "id": "resp_private_identifier",
        "object": "response",
        "status": status,
        "model": "antigravity/gemini-3.7-flash-tiered",
        "output": list(output),
        "output_text": output_text,
        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    }


def _stream_response(response):
    payload = {
        "type": "response.completed",
        "sequence_number": 7,
        "response": response,
    }

    async def body():
        yield f"event: response.completed\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(body(), media_type="text/event-stream")


def _fake_request(app):
    return type("VerificationRequest", (), {"app": app})()


def _fake_app(tmp_path):
    credential = AntigravityCredential(
        id="personal-email@example.com",
        client_id="client-private",
        client_secret="client-secret-private",
        refresh_token="refresh-private",
        access_token="access-private",
        expires_at=9999999999.0,
        project="project-private",
    )
    pool = CredentialPool()
    pool.add_antigravity(credential)

    class Adapter:
        async def refresh_credential(self, pooled):
            assert pooled.id == credential.id

        async def check_control_plane(self, pooled, client):
            return httpx.Response(200, json={"private": "control-secret"})

        async def fetch_quota(self, pooled, client):
            return {
                "credential_id": credential.id,
                "source": "daily",
                "mode": "grouped",
                "groups": [{
                    "kind": "gemini",
                    "buckets": [
                        {"window": "5h", "remaining_percent": 80},
                        {"window": "weekly", "remaining_percent": 60},
                    ],
                }],
            }

    state = type("State", (), {})()
    state.pool = pool
    state.antigravity = Adapter()
    state.config = type("Config", (), {"proxy": ""})()
    state.upstream_client_factory = lambda proxy_url=None: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, request=request)),
        trust_env=False,
    )
    return type("App", (), {"state": state})(), credential


def test_response_fingerprint_contains_structure_not_values():
    response = _completed_response(
        {
            "id": "msg_private",
            "type": "message",
            "content": [{"type": "output_text", "text": "generated-secret"}],
        },
        output_text="generated-secret",
    )

    fingerprint = fingerprint_response(response)
    serialized = json.dumps(fingerprint)

    assert fingerprint == {
        "object": "response",
        "status": "completed",
        "output_item_types": ["message"],
        "content_part_types": ["output_text"],
        "has_output_text": True,
        "usage_fields": ["input_tokens", "output_tokens", "total_tokens"],
    }
    assert "generated-secret" not in serialized
    assert "msg_private" not in serialized


@pytest.mark.asyncio
async def test_full_verification_is_staged_pinned_and_redacted(monkeypatch, tmp_path):
    app, credential = _fake_app(tmp_path)
    calls = []

    async def run_responses(request, body, *, credential_id=None, provider=None):
        assert credential_id == credential.id
        assert provider == "antigravity"
        calls.append(body)
        if len(calls) == 1:
            return JSONResponse(content=_completed_response(
                {
                    "id": "msg_private",
                    "type": "message",
                    "content": [{"type": "output_text", "text": "NONSTREAM_PRIVATE"}],
                },
                output_text="NONSTREAM_PRIVATE",
            ))
        if len(calls) == 2:
            return _stream_response(_completed_response(
                {
                    "id": "rs_private",
                    "type": "reasoning",
                    "encrypted_content": "thought-signature-private",
                    "summary": [],
                },
                {
                    "id": "call_private",
                    "type": "function_call",
                    "call_id": "call_private",
                    "name": "list_files",
                    "arguments": '{"path":"."}',
                    "extra_content": {"google": {"thought_signature": "thought-signature-private"}},
                },
            ))
        assert any(item.get("type") == "function_call_output" for item in body["input"])
        return _stream_response(_completed_response(
            {
                "id": "msg_final_private",
                "type": "message",
                "content": [{"type": "output_text", "text": "DONE_PRIVATE"}],
            },
            output_text="DONE_PRIVATE",
        ))

    monkeypatch.setattr("hakimi_proxy.verification._run_responses", run_responses)

    report = await run_full_verification(_fake_request(app), credential.id)

    assert report["status"] == "passed"
    assert [stage["name"] for stage in report["stages"]] == [
        "local",
        "oauth",
        "control_plane",
        "quota",
        "responses_nonstream",
        "responses_stream",
        "agent_replay",
    ]
    assert all(stage["status"] == "passed" for stage in report["stages"])
    assert report["summary"]["inference_requests"] == 3
    assert report["summary"]["leaked_leases"] == 0
    assert report["credential_ref"].startswith("sha256:")
    assert len(calls) == 3
    assert calls[0]["input"] == [
        {"type": "message", "role": "user", "content": "Reply exactly: OK"}
    ]
    assert "tool_choice" not in calls[0]
    assert calls[1]["input"] == [{
        "type": "message",
        "role": "user",
        "content": "Call the list_files function for '.'. Do not answer directly.",
    }]
    assert calls[1]["tool_choice"] == {
        "type": "function",
        "name": "list_files",
    }
    assert calls[2]["input"][0] == calls[1]["input"][0]
    assert "tool_choice" not in calls[2]
    serialized = json.dumps(report)
    for secret in (
        credential.id,
        credential.client_id,
        credential.client_secret,
        credential.refresh_token,
        credential.access_token,
        credential.project,
        "NONSTREAM_PRIVATE",
        "DONE_PRIVATE",
        "call_private",
        "thought-signature-private",
        "control-secret",
    ):
        assert secret not in serialized
    replay = replay_verification_report(report)
    assert replay == {
        "status": "valid",
        "report_status": "passed",
        "schema_version": 1,
        "fingerprint_version": 1,
        "stage_count": 7,
    }


@pytest.mark.asyncio
async def test_full_verification_rejects_nonstream_without_visible_text(monkeypatch, tmp_path):
    app, credential = _fake_app(tmp_path)
    calls = 0

    async def run_responses(request, body, *, credential_id=None, provider=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return JSONResponse(content=_completed_response(
                {"type": "message", "content": []},
                output_text="",
            ))
        if calls == 2:
            return _stream_response(_completed_response({
                "type": "function_call",
                "call_id": "call_safe",
                "name": "list_files",
                "arguments": '{"path":"."}',
                "extra_content": {"google": {"thought_signature": "signature"}},
            }))
        return _stream_response(_completed_response(
            {"type": "message", "content": [{"type": "output_text", "text": "DONE"}]},
            output_text="DONE",
        ))

    monkeypatch.setattr("hakimi_proxy.verification._run_responses", run_responses)

    report = await run_full_verification(_fake_request(app), credential.id)

    stage = next(item for item in report["stages"] if item["name"] == "responses_nonstream")
    assert report["status"] == "failed"
    assert stage["status"] == "failed"
    assert stage["evidence"]["error_type"] == "missing_output_text"
    assert calls == 3


@pytest.mark.asyncio
async def test_full_verification_rejects_stream_without_thought_signature(monkeypatch, tmp_path):
    app, credential = _fake_app(tmp_path)
    calls = 0

    async def run_responses(request, body, *, credential_id=None, provider=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return JSONResponse(content=_completed_response(
                {"type": "message", "content": [{"type": "output_text", "text": "OK"}]},
                output_text="OK",
            ))
        if calls == 2:
            return _stream_response(_completed_response({
                "type": "function_call",
                "call_id": "call_safe",
                "name": "list_files",
                "arguments": '{"path":"."}',
            }))
        return _stream_response(_completed_response(
            {"type": "message", "content": [{"type": "output_text", "text": "DONE"}]},
            output_text="DONE",
        ))

    monkeypatch.setattr("hakimi_proxy.verification._run_responses", run_responses)

    report = await run_full_verification(_fake_request(app), credential.id)

    stage = next(item for item in report["stages"] if item["name"] == "responses_stream")
    assert report["status"] == "failed"
    assert stage["status"] == "failed"
    assert stage["evidence"]["error_type"] == "missing_thought_signature"
    assert calls == 3


@pytest.mark.asyncio
async def test_full_verification_rejects_agent_replay_without_final_message(monkeypatch, tmp_path):
    app, credential = _fake_app(tmp_path)
    calls = 0

    async def run_responses(request, body, *, credential_id=None, provider=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return JSONResponse(content=_completed_response(
                {"type": "message", "content": [{"type": "output_text", "text": "OK"}]},
                output_text="OK",
            ))
        if calls == 2:
            return _stream_response(_completed_response({
                "type": "function_call",
                "call_id": "call_safe",
                "name": "list_files",
                "arguments": '{"path":"."}',
                "extra_content": {"google": {"thought_signature": "signature"}},
            }))
        return _stream_response(_completed_response(
            {"type": "message", "content": []},
            output_text="",
        ))

    monkeypatch.setattr("hakimi_proxy.verification._run_responses", run_responses)

    report = await run_full_verification(_fake_request(app), credential.id)

    stage = next(item for item in report["stages"] if item["name"] == "agent_replay")
    assert report["status"] == "failed"
    assert stage["status"] == "failed"
    assert stage["evidence"]["error_type"] == "missing_final_message"
    assert calls == 3


@pytest.mark.asyncio
async def test_quota_failure_is_safe_and_does_not_hide_inference_result(monkeypatch, tmp_path):
    app, credential = _fake_app(tmp_path)

    async def fail_quota(pooled, client):
        raise UpstreamError(UpstreamFailure(
            "upstream_request_error",
            "provider echoed refresh-private and personal-email@example.com",
            upstream_status=400,
        ))

    app.state.antigravity.fetch_quota = fail_quota
    calls = 0

    async def run_responses(request, body, *, credential_id=None, provider=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return JSONResponse(content=_completed_response(
                {"type": "message", "content": [{"type": "output_text", "text": "OK"}]},
                output_text="OK",
            ))
        if calls == 2:
            return _stream_response(_completed_response(
                {"type": "reasoning", "encrypted_content": "signature", "summary": []},
                {
                    "type": "function_call",
                    "call_id": "call_safe",
                    "name": "list_files",
                    "arguments": '{"path":"."}',
                    "extra_content": {"google": {"thought_signature": "signature"}},
                },
            ))
        return _stream_response(_completed_response(
            {"type": "message", "content": [{"type": "output_text", "text": "DONE"}]},
            output_text="DONE",
        ))

    monkeypatch.setattr("hakimi_proxy.verification._run_responses", run_responses)

    report = await run_full_verification(_fake_request(app), credential.id)

    quota = next(stage for stage in report["stages"] if stage["name"] == "quota")
    assert report["status"] == "failed"
    assert quota == {
        "name": "quota",
        "status": "failed",
        "latency_ms": quota["latency_ms"],
        "evidence": {"error_type": "upstream_request_error", "upstream_status": 400},
    }
    assert calls == 3
    assert "refresh-private" not in json.dumps(report)


@pytest.mark.asyncio
async def test_selected_credential_lease_leak_fails_verification(monkeypatch, tmp_path):
    app, credential = _fake_app(tmp_path)

    async def leak_release(pooled):
        assert pooled.id == credential.id

    app.state.pool.release = leak_release
    calls = 0

    async def run_responses(request, body, *, credential_id=None, provider=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return JSONResponse(content=_completed_response(
                {"type": "message", "content": [{"type": "output_text", "text": "OK"}]},
                output_text="OK",
            ))
        if calls == 2:
            return _stream_response(_completed_response({
                "type": "function_call",
                "call_id": "call_safe",
                "name": "list_files",
                "arguments": '{"path":"."}',
                "extra_content": {"google": {"thought_signature": "signature"}},
            }))
        return _stream_response(_completed_response(
            {"type": "message", "content": [{"type": "output_text", "text": "DONE"}]},
            output_text="DONE",
        ))

    monkeypatch.setattr("hakimi_proxy.verification._run_responses", run_responses)

    report = await run_full_verification(_fake_request(app), credential.id)

    assert report["status"] == "failed"
    assert report["summary"]["leaked_leases"] == 1


@pytest.mark.asyncio
async def test_full_verification_releases_lease_when_stream_exceeds_limit(monkeypatch, tmp_path):
    app, credential = _fake_app(tmp_path)

    async def oversized_body():
        leased = await app.state.pool.acquire(
            kind="antigravity", credential_id=credential.id
        )
        try:
            yield b"x" * (256 * 1024 + 1)
        finally:
            await app.state.pool.release(leased)

    oversized = StreamingResponse(oversized_body(), media_type="text/event-stream")

    async def run_responses(request, body, **kwargs):
        if not body.get("stream"):
            return JSONResponse(content=_completed_response(
                {"type": "message", "content": [{"type": "output_text", "text": "OK"}]},
                output_text="OK",
            ))
        return oversized

    monkeypatch.setattr("hakimi_proxy.verification._run_responses", run_responses)
    try:
        report = await run_full_verification(_fake_request(app), credential.id)
        assert report["status"] == "failed"
        assert report["summary"]["leaked_leases"] == 0
        assert app.state.pool.all_credentials[0].in_flight == 0
    finally:
        await oversized.body_iterator.aclose()


def test_replay_rejects_a_tampered_passing_agent_stage():
    report = {
        "schema_version": 1,
        "fingerprint_version": 1,
        "status": "passed",
        "provider": "antigravity",
        "model": "antigravity/gemini-3.7-flash-tiered",
        "credential_ref": "sha256:0123456789abcdef",
        "generated_at": "2026-08-29T00:00:00+00:00",
        "stages": [
            {"name": name, "status": "passed", "latency_ms": 1}
            for name in (
                "local", "oauth", "control_plane", "quota",
                "responses_nonstream", "responses_stream", "agent_replay",
            )
        ],
        "summary": {"inference_requests": 3, "leaked_leases": 0, "duration_ms": 7},
    }
    report["stages"][-1]["evidence"] = {
        "thought_signature_present": False,
        "tool_result_accepted": True,
        "final_message_present": True,
    }

    with pytest.raises(ValueError, match="thought signature"):
        replay_verification_report(report)


@pytest.mark.parametrize("status", ["passed", "failed"])
def test_replay_rejects_non_object_stages(status):
    stages = [
        {"name": name, "status": "passed"}
        for name in (
            "local", "oauth", "control_plane", "quota",
            "responses_nonstream", "responses_stream", "agent_replay",
        )
    ]
    stages[-1]["evidence"] = {
        "thought_signature_present": True,
        "tool_result_accepted": True,
        "final_message_present": True,
    }
    report = {
        "schema_version": 1,
        "fingerprint_version": 1,
        "status": status,
        "stages": [*stages, None],
    }

    with pytest.raises(ValueError, match="invalid verification stages"):
        replay_verification_report(report)


def test_replay_rejects_a_tampered_passing_response_fingerprint():
    response_fingerprint = {
        "object": "response",
        "status": "completed",
        "output_item_types": ["message"],
        "content_part_types": ["output_text"],
        "has_output_text": True,
        "usage_fields": ["input_tokens", "output_tokens", "total_tokens"],
    }
    report = {
        "schema_version": 1,
        "fingerprint_version": 1,
        "status": "passed",
        "provider": "antigravity",
        "model": "antigravity/gemini-3.7-flash-tiered",
        "credential_ref": "sha256:0123456789abcdef",
        "generated_at": "2026-08-29T00:00:00+00:00",
        "stages": [
            {"name": "local", "status": "passed", "latency_ms": 1},
            {"name": "oauth", "status": "passed", "latency_ms": 1},
            {"name": "control_plane", "status": "passed", "latency_ms": 1},
            {"name": "quota", "status": "passed", "latency_ms": 1},
            {
                "name": "responses_nonstream",
                "status": "passed",
                "latency_ms": 1,
                "evidence": response_fingerprint,
            },
            {
                "name": "responses_stream",
                "status": "passed",
                "latency_ms": 1,
                "evidence": {
                    "object": "response",
                    "status": "completed",
                    "output_item_types": ["reasoning", "function_call"],
                    "content_part_types": [],
                    "has_output_text": False,
                    "usage_fields": ["input_tokens", "output_tokens", "total_tokens"],
                    "function_call_present": True,
                    "thought_signature_present": True,
                },
            },
            {
                "name": "agent_replay",
                "status": "passed",
                "latency_ms": 1,
                "evidence": {
                    "thought_signature_present": True,
                    "tool_result_accepted": True,
                    "final_message_present": True,
                    "response": response_fingerprint,
                },
            },
        ],
        "summary": {"inference_requests": 3, "leaked_leases": 0, "duration_ms": 7},
    }
    report["stages"][4]["evidence"]["has_output_text"] = False

    with pytest.raises(ValueError, match="non-stream"):
        replay_verification_report(report)
