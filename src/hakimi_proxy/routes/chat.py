"""POST /v1/chat/completions route with failover and metering."""

from __future__ import annotations

import json
import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from hakimi_proxy.adapters.aistudio import AIStudioAdapter
from hakimi_proxy.adapters.antigravity import AntigravityAdapter, _gemini_to_openai
from hakimi_proxy.adapters.base import UpstreamAdapter
from hakimi_proxy.access import UserUsageSink
from hakimi_proxy.adapters.remote import RemoteAdapter
from hakimi_proxy.errors import (
    UpstreamFailure,
    UpstreamError,
    classify_exception,
    classify_streaming_response,
)
from hakimi_proxy.metering.models import UsageRecord
from hakimi_proxy.metering.pricing import compute_cost_for_model
from hakimi_proxy.pool import CredentialPool, CredentialUnavailable, PooledCredential

logger = logging.getLogger(__name__)
router = APIRouter()


def _select_adapter(model: str, aistudio: AIStudioAdapter, antigravity: AntigravityAdapter) -> UpstreamAdapter:
    """Pick the adapter for a model, preferring AI Studio (simpler path)."""
    provider = model.partition("/")[0]
    if provider == "antigravity":
        return antigravity
    if provider == "aistudio":
        return aistudio
    if aistudio.supports_model(model):
        return aistudio
    if antigravity.supports_model(model):
        return antigravity
    return aistudio


def _record_usage(store, cred: PooledCredential, model: str, adapter: UpstreamAdapter, usage: dict) -> None:
    """Build a UsageRecord and persist it."""
    if not usage:
        return
    try:
        rec = UsageRecord.from_openai_usage(credential_id=cred.id, model=model, upstream=adapter.kind, usage=usage)
        rec.cost_usd = compute_cost_for_model(model, rec.tokens)
        store.record(rec)
    except Exception as exc:
        logger.error("Usage recording failed (%s)", type(exc).__name__)


async def _cleanup(resp, client, pool, cred) -> None:
    """Attempt every cleanup operation; preserve cancellation after cleanup."""
    async def close_all():
        cancellation = None
        for resource in (resp, client):
            if resource is not None:
                try:
                    await asyncio.wait_for(resource.aclose(), timeout=5.0)
                except asyncio.CancelledError as exc:
                    cancellation = exc
                except Exception as exc:
                    logger.error("Upstream close failed (%s)", type(exc).__name__)
        if pool is not None:
            await pool.release(cred)
        if cancellation is not None:
            raise cancellation

    task = asyncio.create_task(close_all())
    cancellation = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = exc
    try:
        task.result()
    finally:
        if cancellation is not None:
            raise cancellation


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    return await _run_chat_completion(request, body)


async def _run_chat_completion(
    request: Request,
    body: dict,
    *,
    credential_id: str | None = None,
    provider: str | None = None,
):
    """Run the shared upstream Chat Completions path for any facade."""
    model = body.get("model", "gemini-3.7-flash")
    if not isinstance(model, str) or not model:
        return JSONResponse(status_code=400, content={'error': {'message': 'model must be a nonempty string'}})
    stream = body.get("stream", False)

    pool: CredentialPool = request.app.state.pool
    store = request.app.state.store
    user_key = getattr(getattr(request, 'state', None), 'user_key', None)
    if user_key:
        if user_key['models'] and model not in user_key['models']:
            return JSONResponse(status_code=403, content={'error': {'message': 'Model not allowed', 'type': 'access_error'}})
        store = UserUsageSink(store, request.app.state.access, user_key['id'])
    aistudio: AIStudioAdapter = request.app.state.aistudio
    antigravity: AntigravityAdapter = request.app.state.antigravity
    max_retries: int = request.app.state.max_retries

    if model.startswith('remote/') and provider is None:
        parts = model.split('/', 2)
        if len(parts) != 3 or not any(c.group == parts[1] and parts[2] in c.models for c in request.app.state.config.remote_credentials):
            return JSONResponse(status_code=404, content={'error': {'message': 'Remote model not configured'}})
        adapter = RemoteAdapter(parts[1], request.app.state.config.proxy)
    elif provider == "antigravity":
        adapter = antigravity
    elif provider == "aistudio":
        adapter = aistudio
    else:
        adapter = _select_adapter(model, aistudio, antigravity)

    journal = getattr(request.app.state, "diagnostics", None)
    request_id = getattr(getattr(request, "state", None), "request_id", "")
    attempt = 0
    attempt_limit = 1 if credential_id else max_retries
    last_failure = UpstreamFailure("no_available_credentials", "All retries exhausted: No available credentials")
    queue_deadline = time.monotonic() + 30.0

    while attempt < attempt_limit:
        attempt += 1
        try:
            adapter, cred = await _acquire_for_request(
                pool,
                adapter,
                aistudio,
                antigravity,
                model,
                queue_deadline,
                credential_id=credential_id,
            )
        except CredentialUnavailable as exc:
            if exc.reason == "busy_timeout":
                return _failure_response(UpstreamFailure("capacity_exhausted", "All matching credentials are busy"), 503)
            return _failure_response(last_failure, 503)

        started = time.perf_counter()
        proxy_url = request.app.state.config.proxy or None
        client = None
        resp: httpx.Response | None = None
        stream_owns_resources = False
        try:
            client = request.app.state.upstream_client_factory(proxy_url)
            resp = await adapter.forward(body, cred, stream, client)
            if resp.status_code != 200:
                failure = await classify_streaming_response(resp)
                _apply_failure(pool, cred, failure, model, started, journal=journal, request_id=request_id)
                last_failure = failure
                if failure.retryable or failure.credential_action != "none":
                    continue
                return _failure_response(failure, 502 if failure.type != "proxy_error" else 500)

            if stream:
                stream_iter, prefetched_lines = await _prepare_stream(resp, adapter)
                result = _stream_response(
                    resp,
                    adapter,
                    cred,
                    model,
                    store,
                    client,
                    stream_iter=stream_iter,
                    prefetched_lines=prefetched_lines,
                    pool=pool,
                    started_at=started,
                    journal=journal,
                    request_id=request_id,
                )
                stream_owns_resources = True
                return result

            resp_body = await _non_stream_response(resp, adapter, cred, model, store)
            pool.mark_success(cred, latency_ms=_latency_ms(started), model=model)
            return resp_body
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = classify_exception(exc)
            logger.warning("Request to %s failed: %s", cred.id, failure.message)
            _apply_failure(pool, cred, failure, model, started, journal=journal, request_id=request_id)
            last_failure = failure
            if failure.retryable or failure.credential_action != "none":
                continue
            return _failure_response(failure, 502 if failure.type != "proxy_error" else 500)
        finally:
            if not stream_owns_resources:
                await _cleanup(resp, client, pool, cred)

    return _failure_response(last_failure, 503)


def _latency_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _failure_response(failure: UpstreamFailure, status_code: int) -> JSONResponse:
    headers = {"Retry-After": str(max(1, failure.retry_after or 2))} if status_code == 503 else {}
    return JSONResponse(status_code=status_code, content={"error": failure.public()}, headers=headers)


def _apply_failure(pool: CredentialPool, cred: PooledCredential, failure: UpstreamFailure, model: str, started: float, *, journal=None, request_id="") -> None:
    if journal is not None:
        journal.record("upstream_failure", level="warning", request_id=request_id,
                       model=model, failure_type=failure.type,
                       upstream_status=failure.upstream_status or 0,
                       cooldown_scope=failure.cooldown_scope,
                       duration_ms=_latency_ms(started))
    pool.mark_failure(cred, failure.type, failure.message, latency_ms=_latency_ms(started), model=model)
    if failure.credential_action == "cooldown":
        delay = failure.retry_after
        if delay is None and failure.type in {"upstream_server_error", "upstream_transport_error"}:
            delay = 2
        pool.mark_cooldown(cred, delay, model=model if failure.cooldown_scope == "model" else None)
    elif failure.credential_action == "disable":
        pool.mark_disabled(cred)


async def _acquire_for_request(
    pool: CredentialPool,
    adapter: UpstreamAdapter,
    aistudio: AIStudioAdapter,
    antigravity: AntigravityAdapter,
    model: str,
    deadline: float,
    *,
    credential_id: str | None = None,
) -> tuple[UpstreamAdapter, PooledCredential]:
    """Prefer the selected adapter, then try a compatible fallback before waiting."""
    if adapter.kind.startswith('remote:'):
        return adapter, await pool.acquire(kind=adapter.kind, timeout_seconds=max(0, deadline - time.monotonic()), model=model)
    if credential_id:
        remaining = max(0.0, deadline - time.monotonic())
        return adapter, await pool.acquire(
            kind=adapter.kind,
            credential_id=credential_id,
            timeout_seconds=remaining,
            model=model,
        )
    ordered = [adapter]
    other = antigravity if adapter.kind == "aistudio" else aistudio
    if other.supports_model(model):
        ordered.append(other)
    busy: list[UpstreamAdapter] = []
    for candidate in ordered:
        try:
            return candidate, await pool.acquire(kind=candidate.kind, timeout_seconds=0, model=model)
        except CredentialUnavailable as exc:
            if exc.reason in {"busy_timeout", "cooldown"}:
                busy.append(candidate)

    for candidate in busy:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            break
        try:
            return candidate, await pool.acquire(kind=candidate.kind, timeout_seconds=remaining, model=model)
        except CredentialUnavailable:
            continue
    raise CredentialUnavailable("busy_timeout" if busy else "unavailable")


async def _non_stream_response(resp: httpx.Response, adapter: UpstreamAdapter, cred: PooledCredential, model: str, store) -> JSONResponse:
    """Handle a non-streaming response: parse, record usage, return."""
    try:
        raw_body = resp.json()
    except (ValueError, TypeError) as exc:
        raise UpstreamError(
            UpstreamFailure("upstream_invalid_response", f"Upstream returned invalid JSON: {type(exc).__name__}")
        ) from exc

    if adapter.kind == "antigravity":
        body = _gemini_to_openai(raw_body, model)
        usage = adapter.extract_usage(raw_body)
    else:
        body = raw_body
        usage = adapter.extract_usage(body)

    choices = body.get("choices") or []
    terminal_empty = bool(choices and choices[0].get("finish_reason") in {"length", "content_filter"})
    if not _has_usable_output(body) and not terminal_empty:
        raise UpstreamError(UpstreamFailure("empty_upstream_response", "Upstream returned no text, reasoning, or tool call"))

    _record_usage(store, cred, model, adapter, usage)
    return JSONResponse(content=body)


async def _prepare_stream(resp: httpx.Response, adapter: UpstreamAdapter) -> tuple[AsyncIterator[str], list[str]]:
    """Read through the first valid upstream event before declaring stream success."""
    stream_iter = resp.aiter_lines()
    prefetched: list[str] = []
    saw_meaningful = False
    try:
        async for line in stream_iter:
            prefetched.append(line)
            transformed, _ = adapter.transform_stream_line(line)
            if not transformed:
                continue
            try:
                payload = json.loads(transformed)
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict) and payload.get("error"):
                error = payload["error"] if isinstance(payload["error"], dict) else {}
                status = int(error.get("code", 502) or 502)
                raise UpstreamError(UpstreamFailure("upstream_request_error", str(error.get("message") or "Upstream stream returned an error")[:240], status))
            choices = payload.get("choices") if isinstance(payload, dict) else []
            choice = choices[0] if choices and isinstance(choices[0], dict) else {}
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            if delta.get("content") or delta.get("reasoning_content") or delta.get("tool_calls") or delta.get("na2h_thought_signatures"):
                saw_meaningful = True
            if saw_meaningful:
                return stream_iter, prefetched
            if choice.get("finish_reason"):
                if choice["finish_reason"] in {"length", "content_filter"}:
                    return stream_iter, prefetched
                raise UpstreamError(UpstreamFailure("empty_upstream_response", "Upstream stream finished without usable output"))
    except (asyncio.CancelledError, UpstreamError):
        raise
    except Exception as exc:
        raise UpstreamError(
            UpstreamFailure("upstream_transport_error", f"{type(exc).__name__}: stream failed before first event", None, True, "cooldown")
        ) from exc
    raise UpstreamError(UpstreamFailure("empty_upstream_response", "Upstream stream ended without usable output"))


def _has_usable_output(body: dict) -> bool:
    choices = body.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return False
    message = choices[0].get("message") or {}
    return bool(
        message.get("content")
        or message.get("reasoning_content")
        or message.get("tool_calls")
    )


def _stream_response(
    resp: httpx.Response,
    adapter: UpstreamAdapter,
    cred: PooledCredential,
    model: str,
    store,
    client: httpx.AsyncClient,
    *,
    stream_iter: AsyncIterator[str] | None = None,
    prefetched_lines: list[str] | None = None,
    pool: CredentialPool | None = None,
    started_at: float | None = None,
    journal=None,
    request_id="",
) -> StreamingResponse:
    """Handle a streaming response: forward SSE, capture usage, record."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    captured_usage: dict | None = None
    saw_finish_reason = False
    saw_upstream_event = False

    async def upstream_lines():
        for line in prefetched_lines or []:
            yield line
        source = stream_iter or resp.aiter_lines()
        try:
            async for line in source:
                yield line
        except (asyncio.CancelledError, UpstreamError):
            raise
        except Exception as exc:
            raise UpstreamError(
                UpstreamFailure("upstream_transport_error", f"{type(exc).__name__}: stream connection failed", None, True, "cooldown")
            ) from exc

    async def generate():
        nonlocal captured_usage, saw_finish_reason, saw_upstream_event
        try:
            initial = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(initial)}\n\n"

            async for line in upstream_lines():
                transformed, usage = adapter.transform_stream_line(line)
                if usage:
                    captured_usage = usage
                if transformed:
                    saw_upstream_event = True
                    try:
                        chunk = json.loads(transformed)
                        if chunk.get("error"):
                            raise UpstreamError(UpstreamFailure(
                                "upstream_error", "Upstream reported a stream error"
                            ))
                        if adapter.kind == "antigravity":
                            chunk["id"] = chunk_id
                            chunk["model"] = model
                            transformed = json.dumps(chunk)
                        saw_finish_reason = saw_finish_reason or any(
                            choice.get("finish_reason") is not None
                            for choice in chunk.get("choices", [])
                        )
                    except json.JSONDecodeError:
                        pass
                    yield f"data: {transformed}\n\n"

            if not saw_finish_reason:
                raise UpstreamError(UpstreamFailure(
                    "upstream_incomplete_response", "Upstream ended without a finish reason"
                ))
            yield "data: [DONE]\n\n"
            if pool is not None:
                pool.mark_success(cred, latency_ms=_latency_ms(started_at or time.perf_counter()), model=model)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = classify_exception(exc)
            if pool is not None:
                _apply_failure(pool, cred, failure, model, started_at or time.perf_counter(), journal=journal, request_id=request_id)
            if not saw_upstream_event:
                raise
            error = {
                "error": {
                    "message": "Upstream stream failed after output started",
                    "type": "upstream_error",
                    "detail": type(exc).__name__,
                }
            }
            yield f"data: {json.dumps(error)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            try:
                if captured_usage:
                    _record_usage(store, cred, model, adapter, captured_usage)
            finally:
                await _cleanup(resp, client, pool, cred)

    return StreamingResponse(generate(), media_type="text/event-stream")
