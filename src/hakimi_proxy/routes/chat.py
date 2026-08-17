"""POST /v1/chat/completions route with failover and metering."""

from __future__ import annotations

import json
import logging
import time
import uuid

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from hakimi_proxy.adapters.aistudio import AIStudioAdapter
from hakimi_proxy.adapters.antigravity import AntigravityAdapter, _gemini_to_openai
from hakimi_proxy.adapters.base import UpstreamAdapter
from hakimi_proxy.metering.models import UsageRecord
from hakimi_proxy.metering.pricing import compute_cost_for_model
from hakimi_proxy.pool import CredentialPool, PooledCredential

logger = logging.getLogger(__name__)
router = APIRouter()


def _select_adapter(model: str, aistudio: AIStudioAdapter, antigravity: AntigravityAdapter) -> UpstreamAdapter:
    """Pick the adapter for a model, preferring AI Studio (simpler path)."""
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
    model = body.get("model", "gemini-3.6-flash")
    stream = body.get("stream", False)

    pool: CredentialPool = request.app.state.pool
    store = request.app.state.store
    aistudio: AIStudioAdapter = request.app.state.aistudio
    antigravity: AntigravityAdapter = request.app.state.antigravity
    max_retries: int = request.app.state.max_retries

    adapter = _select_adapter(model, aistudio, antigravity)

    attempt = 0
    last_error = "No available credentials"

    while attempt < max_retries:
        attempt += 1
        cred = pool.get_available(kind=adapter.kind)
        if cred is None:
            other = antigravity if adapter.kind == "aistudio" else aistudio
            if other.supports_model(model):
                adapter = other
                cred = pool.get_available(kind=adapter.kind)
            if cred is None:
                break

        proxy_url = request.app.state.config.proxy or None
        client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else httpx.AsyncClient()
        try:
            resp = await adapter.forward(body, cred, stream, client)
        except Exception as e:
            logger.warning("Request to %s failed: %s", cred.id, e)
            pool.mark_cooldown(cred)
            last_error = str(e)
            await client.aclose()
            continue

        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("retry-after"))
            pool.mark_cooldown(cred, retry_after)
            last_error = f"Rate limited: {cred.id}"
            await resp.aclose()
            await client.aclose()
            continue

        if resp.status_code in (401, 403):
            pool.mark_disabled(cred)
            last_error = f"Auth failure: {cred.id}"
            await resp.aclose()
            await client.aclose()
            continue

        if resp.status_code >= 500:
            pool.mark_cooldown(cred)
            last_error = f"Server error {resp.status_code}: {cred.id}"
            await resp.aclose()
            await client.aclose()
            continue

        if resp.status_code != 200:
            last_error = f"Upstream returned {resp.status_code}: {cred.id}"
            try:
                err_body = resp.json()
                last_error += f" -- {json.dumps(err_body)[:200]}"
            except Exception:
                pass
            await resp.aclose()
            await client.aclose()
            continue

        # Success
        if stream:
            return _stream_response(resp, adapter, cred, model, store, client)
        else:
            resp_body = await _non_stream_response(resp, adapter, cred, model, store)
            await resp.aclose()
            await client.aclose()
            return resp_body

    return JSONResponse(
        status_code=503,
        content={"error": {"message": f"All retries exhausted: {last_error}", "type": "upstream_error"}},
    )


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


async def _non_stream_response(resp: httpx.Response, adapter: UpstreamAdapter, cred: PooledCredential, model: str, store) -> JSONResponse:
    """Handle a non-streaming response: parse, record usage, return."""
    raw_body = resp.json()

    if adapter.kind == "antigravity":
        body = _gemini_to_openai(raw_body, model)
        usage = adapter.extract_usage(raw_body)
    else:
        body = raw_body
        usage = adapter.extract_usage(body)

    _record_usage(store, cred, model, adapter, usage)
    return JSONResponse(content=body)


def _stream_response(resp: httpx.Response, adapter: UpstreamAdapter, cred: PooledCredential, model: str, store, client: httpx.AsyncClient) -> StreamingResponse:
    """Handle a streaming response: forward SSE, capture usage, record."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    captured_usage: dict | None = None

    async def generate():
        nonlocal captured_usage
        try:
            initial = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(initial)}\n\n"

            async for line in resp.aiter_lines():
                transformed, usage = adapter.transform_stream_line(line)
                if usage:
                    captured_usage = usage
                if transformed:
                    if adapter.kind == "antigravity":
                        try:
                            chunk = json.loads(transformed)
                            chunk["id"] = chunk_id
                            chunk["model"] = model
                            transformed = json.dumps(chunk)
                        except json.JSONDecodeError:
                            pass
                    yield f"data: {transformed}\n\n"

            final = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(final)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if captured_usage:
                _record_usage(store, cred, model, adapter, captured_usage)
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(generate(), media_type="text/event-stream")
