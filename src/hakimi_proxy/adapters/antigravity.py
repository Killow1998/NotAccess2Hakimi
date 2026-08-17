"""Antigravity adapter: OAuth + Cloud Code API with protocol conversion.

Cloud Code API endpoints (fallback order):
  daily: https://daily-cloudcode-pa.googleapis.com
  prod:  https://cloudcode-pa.googleapis.com

RPC paths:
  Non-stream: /v1internal:generateContent
  Stream:     /v1internal:streamGenerateContent?alt=sse

Request body is wrapped: {project, model, request: {geminiFormat}, userAgent, requestType, requestId}
"""

from __future__ import annotations

import json
import logging
import time
import uuid

import httpx

from hakimi_proxy.adapters.base import UpstreamAdapter
from hakimi_proxy.config import AntigravityCredential
from hakimi_proxy.pool import PooledCredential

logger = logging.getLogger(__name__)

ENDPOINTS = [
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
]

DEFAULT_PROJECT_ID = "rising-fact-p41fc"

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

ANTIGRAVITY_HEADERS = {
    "Content-Type": "application/json",
    "X-Client-Name": "antigravity",
    "X-Client-Version": "0.8.6",
    "x-goog-api-client": "gl-node/18.18.2 fire/0.8.6 grpc/1.10.x",
}

SUPPORTED_MODELS: set[str] = {
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-3.6-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
}


def _openai_to_gemini(body: dict) -> dict:
    """Convert an OpenAI chat completion request to Gemini generateContent format."""
    contents: list[dict] = []
    system_instruction: dict | None = None

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            system_instruction = {"parts": [{"text": content}]}
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})
        else:
            parts_list: list[dict] = []
            if isinstance(content, str):
                parts_list.append({"text": content})
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, str):
                        parts_list.append({"text": part})
                    elif isinstance(part, dict) and part.get("type") == "text":
                        parts_list.append({"text": part["text"]})
            contents.append({"role": "user", "parts": parts_list or [{"text": ""}]})

    gemini_req: dict = {"contents": contents}
    if system_instruction:
        gemini_req["systemInstruction"] = system_instruction

    gen_config: dict = {}
    if "temperature" in body:
        gen_config["temperature"] = body["temperature"]
    if "max_tokens" in body:
        gen_config["maxOutputTokens"] = body["max_tokens"]
    if "top_p" in body:
        gen_config["topP"] = body["top_p"]
    if gen_config:
        gemini_req["generationConfig"] = gen_config

    return gemini_req


def _gemini_to_openai(gemini_body: dict, model: str) -> dict:
    """Convert a Gemini generateContent response to OpenAI chat completion format."""
    candidates = gemini_body.get("candidates", [])
    text = ""
    finish_reason = "stop"
    if candidates:
        first = candidates[0]
        parts = first.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if "text" in p)
        fr = first.get("finishReason", "STOP")
        finish_reason = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
        }.get(fr, "stop")

    usage_meta = gemini_body.get("usageMetadata", {})
    prompt_tokens = usage_meta.get("promptTokenCount", 0)
    completion_tokens = usage_meta.get("candidatesTokenCount", 0)

    return {
        "id": f"chatcmpl-antigravity-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": usage_meta.get("totalTokenCount", prompt_tokens + completion_tokens),
        },
    }


def _gemini_chunk_to_openai_chunk(gemini_data: dict, model: str, chunk_id: str) -> tuple[str | None, dict | None]:
    """Convert one Gemini SSE data chunk to an OpenAI SSE chunk."""
    inner = gemini_data.get("response", gemini_data)
    candidates = inner.get("candidates", [])
    text = ""
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if "text" in p)

    usage_meta = inner.get("usageMetadata")
    usage: dict | None = None
    if usage_meta:
        prompt_tokens = usage_meta.get("promptTokenCount", 0)
        completion_tokens = usage_meta.get("candidatesTokenCount", 0)
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": usage_meta.get("totalTokenCount", prompt_tokens + completion_tokens),
        }

    chunk = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": text} if text else {},
                "finish_reason": None,
            }
        ],
    }
    if usage:
        chunk["usage"] = usage
    return json.dumps(chunk), usage


class AntigravityAdapter(UpstreamAdapter):
    @property
    def kind(self) -> str:
        return "antigravity"

    def supports_model(self, model: str) -> bool:
        stripped = model.split("/")[-1]
        return stripped in SUPPORTED_MODELS or model in SUPPORTED_MODELS

    async def refresh_credential(self, cred: PooledCredential) -> None:
        """Refresh the OAuth access token if expired or about to expire."""
        ag: AntigravityCredential = cred.credential  # type: ignore[attr-defined]
        if ag.access_token and ag.expires_at > time.time() + 300:
            return

        logger.info("Refreshing OAuth token for credential %s", cred.id)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OAUTH_TOKEN_URL,
                data={
                    "client_id": ag.client_id,
                    "client_secret": ag.client_secret,
                    "refresh_token": ag.refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=30.0,
            )
            if resp.status_code != 200:
                logger.error("Token refresh failed for %s: %d %s", cred.id, resp.status_code, resp.text)
                raise RuntimeError(f"OAuth token refresh failed: {resp.status_code}")
            data = resp.json()
            ag.access_token = data["access_token"]
            ag.expires_at = time.time() + data.get("expires_in", 3600)
            logger.info("Token refreshed for %s, expires in %ds", cred.id, data.get("expires_in", 3600))

    async def forward(
        self,
        body: dict,
        cred: PooledCredential,
        stream: bool,
        client: httpx.AsyncClient,
    ) -> httpx.Response:
        await self.refresh_credential(cred)
        ag: AntigravityCredential = cred.credential  # type: ignore[attr-defined]

        model = body.get("model", "gemini-3.7-flash")
        gemini_req = _openai_to_gemini(body)

        payload = {
            "project": DEFAULT_PROJECT_ID,
            "model": model,
            "request": gemini_req,
            "userAgent": "antigravity",
            "requestType": "agent",
            "requestId": f"agent-{uuid.uuid4()}",
        }

        headers = {
            **ANTIGRAVITY_HEADERS,
            "Authorization": f"Bearer {ag.access_token}",
        }

        path = "/v1internal:streamGenerateContent?alt=sse" if stream else "/v1internal:generateContent"
        last_error: Exception | None = None
        for endpoint in ENDPOINTS:
            url = f"{endpoint}{path}"
            try:
                resp = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=httpx.Timeout(120.0, connect=30.0),
                )
                return resp
            except httpx.HTTPError as e:
                logger.warning("Endpoint %s failed for %s: %s", endpoint, cred.id, e)
                last_error = e
                continue

        raise last_error or RuntimeError("All endpoints failed")

    def extract_usage(self, response_body: dict) -> dict:
        """Extract usage from a non-streaming Cloud Code response."""
        inner = response_body.get("response", response_body)
        usage_meta = inner.get("usageMetadata", {})
        prompt_tokens = usage_meta.get("promptTokenCount", 0)
        completion_tokens = usage_meta.get("candidatesTokenCount", 0)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": usage_meta.get("totalTokenCount", prompt_tokens + completion_tokens),
        }

    def transform_stream_line(self, raw_line: str) -> tuple[str | None, dict | None]:
        """Transform a Cloud Code SSE line to OpenAI SSE format."""
        if not raw_line.startswith("data:"):
            return None, None
        data_str = raw_line[5:].strip()
        if not data_str:
            return None, None
        try:
            gemini_data = json.loads(data_str)
        except json.JSONDecodeError:
            return None, None

        chunk_id = f"chatcmpl-antigravity-{uuid.uuid4().hex[:8]}"
        return _gemini_chunk_to_openai_chunk(gemini_data, "", chunk_id)
