"""Manual Antigravity verification with value-free report evidence."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

from hakimi_proxy.errors import (
    UpstreamError,
    UpstreamFailure,
    classify_exception,
    classify_response,
)
from hakimi_proxy.routes.responses import _run_responses


_OUTPUT_ITEM_TYPES = {"message", "reasoning", "function_call", "custom_tool_call"}
_CONTENT_PART_TYPES = {"output_text", "refusal"}
_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "input_tokens_details",
    "output_tokens_details",
)
_MODEL = "antigravity/gemini-3.7-flash-tiered"
_MAX_STREAM_BYTES = 256 * 1024


def fingerprint_response(response: dict[str, Any]) -> dict[str, Any]:
    """Return allowlisted response structure without generated values or IDs."""
    output = response.get("output")
    items = output if isinstance(output, list) else []
    item_types = [
        item_type
        for item in items
        if isinstance(item, dict)
        and isinstance((item_type := item.get("type")), str)
        and item_type in _OUTPUT_ITEM_TYPES
    ]
    content_types = [
        part_type
        for item in items
        if isinstance(item, dict) and isinstance(item.get("content"), list)
        for part in item["content"]
        if isinstance(part, dict)
        and isinstance((part_type := part.get("type")), str)
        and part_type in _CONTENT_PART_TYPES
    ]
    usage = response.get("usage")
    usage_fields = [
        field
        for field in _USAGE_FIELDS
        if isinstance(usage, dict) and field in usage
    ]
    return {
        "object": "response" if response.get("object") == "response" else "unknown",
        "status": response.get("status")
        if response.get("status") in {"completed", "failed", "incomplete"}
        else "unknown",
        "output_item_types": item_types,
        "content_part_types": content_types,
        "has_output_text": bool(response.get("output_text")),
        "usage_fields": usage_fields,
    }


def _latency_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _failure_evidence(exc: BaseException) -> dict[str, Any]:
    failure = classify_exception(exc)
    evidence: dict[str, Any] = {"error_type": failure.type}
    if failure.upstream_status is not None:
        evidence["upstream_status"] = failure.upstream_status
    return evidence


def _stage(
    name: str,
    started: float,
    *,
    status: str = "passed",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "status": status,
        "latency_ms": _latency_ms(started),
    }
    if evidence is not None:
        result["evidence"] = evidence
    return result


def _report_shell(credential_id: str) -> dict[str, Any]:
    reference = hashlib.sha256(credential_id.encode("utf-8")).hexdigest()[:16]
    return {
        "schema_version": 1,
        "fingerprint_version": 1,
        "status": "passed",
        "provider": "antigravity",
        "model": _MODEL,
        "credential_ref": f"sha256:{reference}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stages": [],
        "summary": {
            "inference_requests": 0,
            "leaked_leases": 0,
            "duration_ms": 0,
        },
    }


def _json_response(response: JSONResponse) -> dict[str, Any]:
    try:
        payload = json.loads(response.body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


async def _completed_stream(response: StreamingResponse) -> dict[str, Any]:
    body = bytearray()
    try:
        async for chunk in response.body_iterator:
            encoded = chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk)
            if len(body) + len(encoded) > _MAX_STREAM_BYTES:
                raise ValueError("Responses stream exceeded verification limit")
            body.extend(encoded)
    finally:
        close = getattr(response.body_iterator, "aclose", None)
        if close:
            await close()
    for block in body.decode("utf-8", errors="replace").split("\n\n"):
        for line in block.splitlines():
            if not line.startswith("data:"):
                continue
            value = line[5:].strip()
            if not value or value == "[DONE]":
                continue
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "response.completed":
                completed = payload.get("response")
                return completed if isinstance(completed, dict) else {}
    raise ValueError("Responses stream did not complete")


async def _run_response(
    request: Any,
    body: dict[str, Any],
    credential_id: str,
) -> dict[str, Any]:
    result = await _run_responses(
        request,
        body,
        credential_id=credential_id,
        provider="antigravity",
    )
    if isinstance(result, StreamingResponse):
        if result.status_code != 200:
            raise UpstreamError(classify_response(httpx.Response(result.status_code)))
        return await _completed_stream(result)
    if not isinstance(result, JSONResponse):
        raise TypeError("Responses verifier received an unsupported response")
    payload = _json_response(result)
    if result.status_code != 200:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        raise UpstreamError(_classify_local_error(result.status_code, error))
    return payload


def _thought_signature_present(response: dict[str, Any], call: dict[str, Any]) -> bool:
    if call.get("extra_content", {}).get("google", {}).get("thought_signature"):
        return True
    return any(
        isinstance(item, dict)
        and item.get("type") == "reasoning"
        and bool(item.get("encrypted_content"))
        for item in response.get("output", [])
    )


def _classify_local_error(
    status_code: int,
    error: dict[str, Any],
) -> UpstreamFailure:
    """Classify a local facade error without retaining its message."""
    return classify_response(httpx.Response(status_code, json={"error": error}))


async def run_full_verification(request: Any, credential_id: str) -> dict[str, Any]:
    """Run the bounded manual verification workflow for one Antigravity account."""
    started = time.perf_counter()
    report = _report_shell(credential_id)
    stages: list[dict[str, Any]] = report["stages"]
    pool = request.app.state.pool
    credential = next(
        (
            item
            for item in pool.all_credentials
            if item.kind == "antigravity" and item.id == credential_id
        ),
        None,
    )
    local_started = time.perf_counter()
    if credential is None:
        stages.append(_stage(
            "local",
            local_started,
            status="failed",
            evidence={"error_type": "credential_not_found"},
        ))
        report["status"] = "failed"
        report["summary"]["duration_ms"] = _latency_ms(started)
        return report
    stages.append(_stage("local", local_started))

    setup_ok = True
    leased = None
    client = None
    try:
        leased = await pool.acquire(
            kind="antigravity",
            credential_id=credential_id,
            timeout_seconds=30,
        )
        proxy_url = request.app.state.config.proxy or None
        client = request.app.state.upstream_client_factory(proxy_url)
        adapter = request.app.state.antigravity

        oauth_started = time.perf_counter()
        try:
            await adapter.refresh_credential(leased)
            stages.append(_stage("oauth", oauth_started))
        except Exception as exc:
            stages.append(_stage(
                "oauth", oauth_started, status="failed", evidence=_failure_evidence(exc)
            ))
            setup_ok = False

        if setup_ok:
            control_started = time.perf_counter()
            response = None
            try:
                response = await adapter.check_control_plane(leased, client)
                if response.status_code != 200:
                    raise UpstreamError(classify_response(response))
                stages.append(_stage(
                    "control_plane",
                    control_started,
                    evidence={"http_status": 200},
                ))
            except Exception as exc:
                stages.append(_stage(
                    "control_plane",
                    control_started,
                    status="failed",
                    evidence=_failure_evidence(exc),
                ))
                setup_ok = False
            finally:
                if response is not None:
                    await response.aclose()

        if setup_ok:
            quota_started = time.perf_counter()
            try:
                quota = await adapter.fetch_quota(leased, client)
                groups = quota.get("groups") if isinstance(quota, dict) else None
                raw_mode = quota.get("mode") if isinstance(quota, dict) else None
                mode = raw_mode if raw_mode in {"grouped", "degraded"} else "unknown"
                stages.append(_stage(
                    "quota",
                    quota_started,
                    evidence={
                        "mode": mode,
                        "group_count": len(groups) if isinstance(groups, list) else 0,
                    },
                ))
            except Exception as exc:
                stages.append(_stage(
                    "quota",
                    quota_started,
                    status="failed",
                    evidence=_failure_evidence(exc),
                ))
    except Exception as exc:
        if not any(stage["name"] == "oauth" for stage in stages):
            stages.append(_stage(
                "oauth",
                time.perf_counter(),
                status="failed",
                evidence=_failure_evidence(exc),
            ))
        setup_ok = False
    finally:
        if client is not None:
            await client.aclose()
        if leased is not None:
            await pool.release(leased)

    if setup_ok:
        tool = {
            "type": "function",
            "name": "list_files",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
        nonstream_input = {
            "type": "message",
            "role": "user",
            "content": "Reply exactly: OK",
        }
        tool_input = {
            "type": "message",
            "role": "user",
            "content": "Call the list_files function for '.'. Do not answer directly.",
        }

        nonstream_started = time.perf_counter()
        report["summary"]["inference_requests"] += 1
        try:
            nonstream = await _run_response(request, {
                "model": _MODEL,
                "input": [nonstream_input],
                "max_output_tokens": 512,
            }, credential_id)
            fingerprint = fingerprint_response(nonstream)
            stages.append(_stage(
                "responses_nonstream",
                nonstream_started,
                status="passed" if fingerprint["has_output_text"] else "failed",
                evidence=(
                    fingerprint
                    if fingerprint["has_output_text"]
                    else {"error_type": "missing_output_text", **fingerprint}
                ),
            ))
        except Exception as exc:
            stages.append(_stage(
                "responses_nonstream",
                nonstream_started,
                status="failed",
                evidence=_failure_evidence(exc),
            ))

        stream_started = time.perf_counter()
        report["summary"]["inference_requests"] += 1
        first_completed: dict[str, Any] = {}
        try:
            first_completed = await _run_response(request, {
                "model": _MODEL,
                "input": [tool_input],
                "tools": [tool],
                "tool_choice": {"type": "function", "name": "list_files"},
                "stream": True,
            }, credential_id)
            call = next(
                (
                    item
                    for item in first_completed.get("output", [])
                    if isinstance(item, dict) and item.get("type") == "function_call"
                ),
                {},
            )
            signature_present = _thought_signature_present(first_completed, call)
            stream_error = (
                "missing_function_call"
                if not call
                else "missing_thought_signature" if not signature_present else ""
            )
            stream_evidence = {
                **fingerprint_response(first_completed),
                "function_call_present": bool(call),
                "thought_signature_present": signature_present,
            }
            stages.append(_stage(
                "responses_stream",
                stream_started,
                status="failed" if stream_error else "passed",
                evidence=(
                    {"error_type": stream_error, **stream_evidence}
                    if stream_error
                    else stream_evidence
                ),
            ))
        except Exception as exc:
            call = {}
            stages.append(_stage(
                "responses_stream",
                stream_started,
                status="failed",
                evidence=_failure_evidence(exc),
            ))

        replay_started = time.perf_counter()
        if call and call.get("call_id"):
            report["summary"]["inference_requests"] += 1
            try:
                final = await _run_response(request, {
                    "model": _MODEL,
                    "input": [
                        tool_input,
                        *first_completed.get("output", []),
                        {
                            "type": "function_call_output",
                            "call_id": call["call_id"],
                            "output": '{"files":["README.md"]}',
                        },
                    ],
                    "tools": [tool],
                    "stream": True,
                }, credential_id)
                final_message_present = bool(final.get("output_text"))
                replay_evidence = {
                    "thought_signature_present": _thought_signature_present(
                        first_completed, call
                    ),
                    "tool_result_accepted": True,
                    "final_message_present": final_message_present,
                    "response": fingerprint_response(final),
                }
                stages.append(_stage(
                    "agent_replay",
                    replay_started,
                    status="passed" if final_message_present else "failed",
                    evidence=(
                        replay_evidence
                        if final_message_present
                        else {"error_type": "missing_final_message", **replay_evidence}
                    ),
                ))
            except Exception as exc:
                stages.append(_stage(
                    "agent_replay",
                    replay_started,
                    status="failed",
                    evidence=_failure_evidence(exc),
                ))
        else:
            stages.append(_stage(
                "agent_replay",
                replay_started,
                status="failed",
                evidence={"error_type": "missing_function_call"},
            ))

    report["summary"]["leaked_leases"] = credential.in_flight
    report["summary"]["duration_ms"] = _latency_ms(started)
    if (
        report["summary"]["leaked_leases"]
        or any(stage["status"] != "passed" for stage in stages)
    ):
        report["status"] = "failed"
    return report


def replay_verification_report(report: dict[str, Any]) -> dict[str, Any]:
    """Validate an allowlisted report without contacting a provider."""
    if report.get("schema_version") != 1:
        raise ValueError("unsupported verification report schema")
    if report.get("fingerprint_version") != 1:
        raise ValueError("unsupported verification fingerprint")
    if report.get("status") not in {"passed", "failed"}:
        raise ValueError("invalid verification report status")
    stages = report.get("stages")
    if not isinstance(stages, list) or any(not isinstance(stage, dict) for stage in stages):
        raise ValueError("invalid verification stages")
    if report["status"] == "passed":
        agent_stage = next(
            (
                stage
                for stage in stages
                if isinstance(stage, dict) and stage.get("name") == "agent_replay"
            ),
            None,
        )
        evidence = agent_stage.get("evidence") if isinstance(agent_stage, dict) else None
        if not isinstance(evidence, dict) or not evidence.get("thought_signature_present"):
            raise ValueError("passing report lacks thought signature evidence")
        if not evidence.get("tool_result_accepted"):
            raise ValueError("passing report lacks accepted tool result evidence")
        if not evidence.get("final_message_present"):
            raise ValueError("passing report lacks final message evidence")
        expected_names = [
            "local",
            "oauth",
            "control_plane",
            "quota",
            "responses_nonstream",
            "responses_stream",
            "agent_replay",
        ]
        if [stage.get("name") for stage in stages if isinstance(stage, dict)] != expected_names:
            raise ValueError("passing report has an invalid stage sequence")
        if any(stage.get("status") != "passed" for stage in stages):
            raise ValueError("passing report contains a failed stage")
        summary = report.get("summary")
        if not isinstance(summary, dict) or summary.get("inference_requests") != 3:
            raise ValueError("passing report has an invalid inference count")
        if summary.get("leaked_leases") != 0:
            raise ValueError("passing report contains a leaked credential lease")

        nonstream = stages[4].get("evidence")
        if (
            not isinstance(nonstream, dict)
            or nonstream.get("object") != "response"
            or nonstream.get("status") != "completed"
            or not nonstream.get("has_output_text")
            or "message" not in nonstream.get("output_item_types", [])
            or "output_text" not in nonstream.get("content_part_types", [])
        ):
            raise ValueError("passing report has an invalid non-stream fingerprint")

        stream = stages[5].get("evidence")
        if (
            not isinstance(stream, dict)
            or stream.get("object") != "response"
            or stream.get("status") != "completed"
            or "function_call" not in stream.get("output_item_types", [])
            or not stream.get("function_call_present")
            or not stream.get("thought_signature_present")
        ):
            raise ValueError("passing report has an invalid streamed tool fingerprint")

        final_response = evidence.get("response")
        if (
            not isinstance(final_response, dict)
            or final_response.get("object") != "response"
            or final_response.get("status") != "completed"
            or not final_response.get("has_output_text")
            or "message" not in final_response.get("output_item_types", [])
        ):
            raise ValueError("passing report has an invalid final response fingerprint")
    return {
        "status": "valid",
        "report_status": report["status"],
        "schema_version": 1,
        "fingerprint_version": 1,
        "stage_count": len(stages),
    }
