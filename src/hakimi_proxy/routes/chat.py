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
from hakimi_proxy.errors import (
    UpstreamFailure,
    UpstreamError,
    classify_exception,
    classify_response,
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
    rec = UsageRecord.from_openai_usage(credential_id=cred.id, model=model, upstream=adapter.kind, usage=usage)
    rec.cost_usd = compute_cost_for_model(model, rec.tokens)
    store.record(rec)


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    return await _run_chat_completion(request, body)


async def _run_chat_completion(request: Request, body: dict):
    """Run the shared upstream Chat Completions path for any facade."""
    model = body.get("model", "gemini-3.7-flash")
    stream = body.get("stream", False)

    pool: CredentialPool = request.app.state.pool
    store = request.app.state.store
    aistudio: AIStudioAdapter = request.app.state.aistudio
    antigravity: AntigravityAdapter = request.app.state.antigravity
    max_retries: int = request.app.state.max_retries

    adapter = _select_adapter(model, aistudio, antigravity)

    attempt = 0
    last_failure = UpstreamFailure("no_available_credentials", "All retries exhausted: No available credentials")
    queue_deadline = time.monotonic() + 30.0

    while attempt < max_retries:
        attempt += 1
        try:
            adapter, cred = await _acquire_for_request(
                pool,
                adapter,
                aistudio,
                antigravity,
                model,
                queue_deadline,
            )
        except CredentialUnavailable as exc:
            if exc.reason == "busy_timeout":
                return _failure_response(UpstreamFailure("capacity_exhausted", "All matching credentials are busy"), 503)
            return _failure_response(last_failure, 503)

        started = time.perf_counter()
        proxy_url = request.app.state.config.proxy or None
        client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else httpx.AsyncClient()
        resp: httpx.Response | None = None
        try:
            resp = await adapter.forward(body, cred, stream, client)
            if resp.status_code != 200:
                failure = classify_response(resp)
                _apply_failure(pool, cred, failure, model, started)
                last_failure = failure
                await resp.aclose()
                await client.aclose()
                await pool.release(cred)
                if failure.retryable or failure.credential_action != "none":
                    continue
                return _failure_response(failure, 502 if failure.type != "proxy_error" else 500)

            if stream:
                stream_iter, prefetched_lines = await _prepare_stream(resp, adapter)
                return _stream_response(
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
                )

            resp_body = await _non_stream_response(resp, adapter, cred, model, store)
            pool.mark_success(cred, latency_ms=_latency_ms(started), model=model)
            await resp.aclose()
            await client.aclose()
            await pool.release(cred)
            return resp_body
        except asyncio.CancelledError:
            if resp is not None:
                await resp.aclose()
            await client.aclose()
            await pool.release(cred)
            raise
        except Exception as exc:
            failure = classify_exception(exc)
            logger.warning("Request to %s failed: %s", cred.id, failure.message)
            _apply_failure(pool, cred, failure, model, started)
            last_failure = failure
            if resp is not None:
                await resp.aclose()
            await client.aclose()
            await pool.release(cred)
            if failure.retryable or failure.credential_action != "none":
                continue
            return _failure_response(failure, 502 if failure.type != "proxy_error" else 500)

    return _failure_response(last_failure, 503)


def _latency_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _failure_response(failure: UpstreamFailure, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": failure.public()})


def _apply_failure(pool: CredentialPool, cred: PooledCredential, failure: UpstreamFailure, model: str, started: float) -> None:
    pool.mark_failure(cred, failure.type, failure.message, latency_ms=_latency_ms(started), model=model)
    if failure.credential_action == "cooldown":
        pool.mark_cooldown(cred, failure.retry_after)
    elif failure.credential_action == "disable":
        pool.mark_disabled(cred)


async def _acquire_for_request(
    pool: CredentialPool,
    adapter: UpstreamAdapter,
    aistudio: AIStudioAdapter,
    antigravity: AntigravityAdapter,
    model: str,
    deadline: float,
) -> tuple[UpstreamAdapter, PooledCredential]:
    """Prefer the selected adapter, then try a compatible fallback before waiting."""
    ordered = [adapter]
    other = antigravity if adapter.kind == "aistudio" else aistudio
    if other.supports_model(model):
        ordered.append(other)
    busy: list[UpstreamAdapter] = []
    for candidate in ordered:
        try:
            return candidate, await pool.acquire(kind=candidate.kind, timeout_seconds=0)
        except CredentialUnavailable as exc:
            if exc.reason == "busy_timeout":
                busy.append(candidate)

    remaining = max(0.0, deadline - time.monotonic())
    for candidate in busy:
        try:
            return candidate, await pool.acquire(kind=candidate.kind, timeout_seconds=remaining)
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

    if not _has_usable_output(body):
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
                final = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(final)}\n\n"
            yield "data: [DONE]\n\n"
            if pool is not None:
                pool.mark_success(cred, latency_ms=_latency_ms(started_at or time.perf_counter()), model=model)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = classify_exception(exc)
            if pool is not None:
                _apply_failure(pool, cred, failure, model, started_at or time.perf_counter())
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
            if captured_usage:
                _record_usage(store, cred, model, adapter, captured_usage)
            await resp.aclose()
            await client.aclose()
            if pool is not None:
                await pool.release(cred)

    return StreamingResponse(generate(), media_type="text/event-stream")
