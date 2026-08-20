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

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable

import httpx

from hakimi_proxy.adapters.base import UpstreamAdapter
from hakimi_proxy.config import AntigravityCredential
from hakimi_proxy.errors import UpstreamError, UpstreamFailure, classify_response
from hakimi_proxy.pool import PooledCredential

logger = logging.getLogger(__name__)

ENDPOINTS = [
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
]

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
LOAD_CODE_ASSIST_URL = "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist"
ONBOARD_USER_URL = "https://daily-cloudcode-pa.googleapis.com/v1internal:onboardUser"
ONBOARD_ATTEMPTS = 5
ONBOARD_POLL_SECONDS = 2

ANTIGRAVITY_HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/json",
    "User-Agent": "antigravity/0.8.6",
    "X-Client-Name": "antigravity",
    "X-Client-Version": "0.8.6",
    "x-goog-api-client": "gl-node/18.18.2 fire/0.8.6 grpc/1.10.x",
}

SUPPORTED_MODELS: set[str] = {
    # The current catalog exposes 3.7 as the tiered model. Keep the
    # product-facing name as an explicit local alias below.
    "gemini-3.7-flash",
    "gemini-3.7-flash-tiered",
    "gemini-3.5-flash",
    "gemini-3.5-flash-extra-low",
    "gemini-3.5-flash-low",
    "gemini-3.1-pro-preview",
    "gemini-3.6-flash",
    "gemini-3.6-flash-high",
    "gemini-3.6-flash-medium",
    "gemini-3.6-flash-low",
    "gemini-3.6-flash-tiered",
    "gemini-3-flash-agent",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
}

ANTIGRAVITY_MODEL_ALIASES = {
    "gemini-3.7-flash": "gemini-3.7-flash-tiered",
}


def _resolve_model_name(model: str) -> str:
    """Resolve only catalog-confirmed display aliases before forwarding."""
    normalized = model.strip().lower()
    return ANTIGRAVITY_MODEL_ALIASES.get(normalized, normalized)


def _json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {"result": value}
    return value if isinstance(value, dict) else {"result": value}


def _content_parts(content) -> list[dict]:
    if isinstance(content, str):
        return [{"text": content}]
    if not isinstance(content, list):
        return []

    parts: list[dict] = []
    for item in content:
        if isinstance(item, str):
            parts.append({"text": item})
            continue
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind in ("text", "input_text"):
            parts.append({"text": item.get("text", "")})
        elif kind == "image_url":
            image = item.get("image_url", {})
            url = image.get("url", "") if isinstance(image, dict) else image
            if isinstance(url, str) and url.startswith("data:") and ";base64," in url:
                header, data = url.split(";base64,", 1)
                parts.append({"inlineData": {"mimeType": header[5:], "data": data}})
            elif url:
                parts.append({"fileData": {"fileUri": url}})
        elif kind == "input_audio" and isinstance(item.get("input_audio"), dict):
            audio = item["input_audio"]
            parts.append({
                "inlineData": {
                    "mimeType": f"audio/{audio.get('format', 'wav')}",
                    "data": audio.get("data", ""),
                }
            })
    return parts


def _openai_to_gemini(body: dict) -> dict:
    """Convert an OpenAI Chat Completions request to Gemini format."""
    contents: list[dict] = []
    system_parts: list[dict] = []
    tool_names: dict[str, str] = {}
    pending_tool_parts: list[dict] = []

    def flush_tool_parts() -> None:
        if pending_tool_parts:
            contents.append({"role": "user", "parts": list(pending_tool_parts)})
            pending_tool_parts.clear()

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        if role in ("system", "developer"):
            system_parts.extend(p for p in _content_parts(msg.get("content")) if "text" in p)
            continue
        if role == "tool":
            name = msg.get("name") or tool_names.get(msg.get("tool_call_id", ""), "unknown")
            response = {
                "name": name,
                "response": _json_object(msg.get("content", "")),
            }
            if msg.get("tool_call_id"):
                response["id"] = msg["tool_call_id"]
            pending_tool_parts.append({"functionResponse": response})
            continue

        flush_tool_parts()
        parts = _content_parts(msg.get("content"))
        if role == "assistant":
            for call in msg.get("tool_calls", []):
                function = call.get("function", {})
                name = function.get("name", "unknown")
                if call.get("id"):
                    tool_names[call["id"]] = name
                function_call = {
                    "name": name,
                    "args": _json_object(function.get("arguments", {})),
                }
                if call.get("id"):
                    function_call["id"] = call["id"]
                part = {"functionCall": function_call}
                signature = call.get("extra_content", {}).get("google", {}).get("thought_signature")
                if signature:
                    part["thoughtSignature"] = signature
                parts.append(part)
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
        else:
            contents.append({"role": "user", "parts": parts or [{"text": ""}]})

    flush_tool_parts()
    gemini_req: dict = {"contents": contents}
    if system_parts:
        gemini_req["systemInstruction"] = {"parts": system_parts}

    gen_config: dict = {}
    if "temperature" in body:
        gen_config["temperature"] = body["temperature"]
    if "max_tokens" in body:
        gen_config["maxOutputTokens"] = body["max_tokens"]
    if "top_p" in body:
        gen_config["topP"] = body["top_p"]
    if "stop" in body:
        gen_config["stopSequences"] = [body["stop"]] if isinstance(body["stop"], str) else body["stop"]
    if "n" in body:
        gen_config["candidateCount"] = body["n"]
    if "frequency_penalty" in body:
        gen_config["frequencyPenalty"] = body["frequency_penalty"]
    if "presence_penalty" in body:
        gen_config["presencePenalty"] = body["presence_penalty"]
    if body.get("reasoning_effort"):
        gen_config["thinkingConfig"] = {"thinkingLevel": body["reasoning_effort"]}
    google_extra = body.get("extra_body", {}).get("google", {})
    if isinstance(google_extra.get("thinking_config"), dict):
        thinking = google_extra["thinking_config"]
        gen_config["thinkingConfig"] = {
            {"thinking_level": "thinkingLevel", "thinking_budget": "thinkingBudget", "include_thoughts": "includeThoughts"}.get(k, k): v
            for k, v in thinking.items()
        }
    response_format = body.get("response_format", {})
    if response_format.get("type") in ("json_object", "json_schema"):
        gen_config["responseMimeType"] = "application/json"
        schema = response_format.get("json_schema", {}).get("schema")
        if schema:
            gen_config["responseJsonSchema"] = schema
    if gen_config:
        gemini_req["generationConfig"] = gen_config

    declarations = []
    for tool in body.get("tools", []):
        if tool.get("type") != "function":
            continue
        function = tool.get("function", {})
        declaration = {"name": function.get("name", "")}
        if function.get("description"):
            declaration["description"] = function["description"]
        if function.get("parameters"):
            declaration["parametersJsonSchema"] = function["parameters"]
        declarations.append(declaration)
    if declarations:
        gemini_req["tools"] = [{"functionDeclarations": declarations}]

    tool_choice = body.get("tool_choice")
    if tool_choice and declarations:
        config: dict = {}
        if tool_choice == "none":
            config["mode"] = "NONE"
        elif tool_choice == "required":
            config["mode"] = "ANY"
        elif isinstance(tool_choice, dict):
            config = {
                "mode": "ANY",
                "allowedFunctionNames": [tool_choice.get("function", {}).get("name", "")],
            }
        else:
            config["mode"] = "AUTO"
        gemini_req["toolConfig"] = {"functionCallingConfig": config}

    return gemini_req


def _gemini_to_openai(gemini_body: dict, model: str) -> dict:
    """Convert a Gemini generateContent response to OpenAI chat completion format."""
    inner = gemini_body.get("response", gemini_body)
    candidates = inner.get("candidates", [])
    text = ""
    finish_reason = "stop"
    message: dict = {"role": "assistant", "content": ""}
    if candidates:
        first = candidates[0]
        parts = first.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
        tool_calls = []
        message_signature = None
        detached_signatures = []
        for part in parts:
            function = part.get("functionCall")
            if function:
                call = {
                    "id": function.get("id") or f"function-call-{uuid.uuid4()}",
                    "type": "function",
                    "function": {
                        "name": function.get("name", ""),
                        "arguments": json.dumps(function.get("args", {}), separators=(",", ":")),
                    },
                }
                if part.get("thoughtSignature"):
                    call["extra_content"] = {"google": {"thought_signature": part["thoughtSignature"]}}
                tool_calls.append(call)
            elif part.get("thoughtSignature"):
                message_signature = part["thoughtSignature"]
                detached_signatures.append(part["thoughtSignature"])
        message = {"role": "assistant", "content": text or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        if message_signature:
            message["extra_content"] = {"google": {"thought_signature": message_signature}}
        if detached_signatures:
            message["na2h_thought_signatures"] = detached_signatures
        fr = first.get("finishReason", "STOP")
        finish_reason = _finish_reason(fr, bool(tool_calls))

    usage_meta = inner.get("usageMetadata", {})
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
                "message": message,
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
    delta: dict = {}
    finish_reason = None
    if candidates:
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
        if text:
            delta["content"] = text
        tool_calls = []
        detached_signatures = []
        for index, part in enumerate(p for p in parts if p.get("functionCall")):
            function = part["functionCall"]
            call = {
                "index": index,
                "id": function.get("id") or f"function-call-{uuid.uuid4()}",
                "type": "function",
                "function": {
                    "name": function.get("name", ""),
                    "arguments": json.dumps(function.get("args", {}), separators=(",", ":")),
                },
            }
            if part.get("thoughtSignature"):
                call["extra_content"] = {"google": {"thought_signature": part["thoughtSignature"]}}
            tool_calls.append(call)
        for part in parts:
            if not part.get("functionCall") and isinstance(part.get("thoughtSignature"), str):
                detached_signatures.append(part["thoughtSignature"])
        if tool_calls:
            delta["tool_calls"] = tool_calls
        if detached_signatures:
            # Internal carrier used by the Responses facade; it preserves
            # CPA-style detached thought signatures across streaming chunks.
            delta["na2h_thought_signatures"] = detached_signatures
        finish_reason = _finish_reason(candidate.get("finishReason"), bool(tool_calls), default=None)

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
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    if usage:
        chunk["usage"] = usage
    return json.dumps(chunk), usage


def _finish_reason(reason: str | None, has_tool_calls: bool, default: str | None = "stop") -> str | None:
    if has_tool_calls:
        return "tool_calls"
    return {
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "content_filter",
        "RECITATION": "content_filter",
    }.get(reason, default)


def _extract_project_id(data: dict) -> str:
    for key in ("cloudaicompanionProject", "projectId", "project"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict) and isinstance(value.get("id"), str) and value["id"].strip():
            return value["id"].strip()
    return ""


def _default_tier_id(data: dict) -> str:
    for tier in data.get("allowedTiers", []):
        if isinstance(tier, dict) and tier.get("isDefault") and tier.get("id"):
            return str(tier["id"]).strip()
    current = data.get("currentTier", {})
    if isinstance(current, dict) and current.get("id"):
        return str(current["id"]).strip() or "free-tier"
    return "free-tier"


class AntigravityAdapter(UpstreamAdapter):
    def __init__(self, proxy: str = "", on_credential_update: Callable[[], None] | None = None) -> None:
        super().__init__(proxy=proxy)
        self.on_credential_update = on_credential_update
        self._refresh_locks: dict[str, asyncio.Lock] = {}

    @property
    def kind(self) -> str:
        return "antigravity"

    def supports_model(self, model: str) -> bool:
        stripped = model.split("/")[-1]
        return _resolve_model_name(stripped) in SUPPORTED_MODELS or model in SUPPORTED_MODELS

    async def refresh_credential(self, cred: PooledCredential) -> None:
        """Refresh the OAuth access token if expired or about to expire."""
        ag: AntigravityCredential = cred.credential  # type: ignore[attr-defined]
        lock = self._refresh_locks.setdefault(cred.id, asyncio.Lock())
        async with lock:
            if ag.access_token and ag.expires_at > time.time() + 300:
                return

            logger.info("Refreshing OAuth token for credential %s", cred.id)
            async with httpx.AsyncClient(proxy=self.proxy or None) as client:
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
                    error_code = ""
                    try:
                        payload = resp.json()
                        if isinstance(payload, dict):
                            error_code = str(payload.get("error") or "").strip()
                    except (ValueError, TypeError):
                        pass
                    suffix = f" ({error_code})" if error_code else ""
                    logger.error("Token refresh failed for %s: %d%s", cred.id, resp.status_code, suffix)
                    failure = classify_response(resp)
                    if error_code in {"invalid_grant", "invalid_client"}:
                        failure = UpstreamFailure(
                            "upstream_auth_error",
                            "OAuth refresh token is no longer valid; authorize this Antigravity account again",
                            resp.status_code,
                            False,
                            "disable",
                        )
                    raise UpstreamError(failure)
                data = resp.json()
                ag.access_token = data["access_token"]
                ag.expires_at = time.time() + float(data.get("expires_in", 3600))
                rotated_refresh_token = data.get("refresh_token")
                if isinstance(rotated_refresh_token, str) and rotated_refresh_token.strip():
                    ag.refresh_token = rotated_refresh_token.strip()
                    if self.on_credential_update:
                        self.on_credential_update()
                logger.info("Token refreshed for %s, expires in %ds", cred.id, data.get("expires_in", 3600))

    @staticmethod
    def _headers(access_token: str) -> dict[str, str]:
        return {**ANTIGRAVITY_HEADERS, "Authorization": f"Bearer {access_token}"}

    async def _ensure_project(
        self, ag: AntigravityCredential, client: httpx.AsyncClient
    ) -> str | httpx.Response:
        if ag.project:
            return ag.project

        response = await client.post(
            LOAD_CODE_ASSIST_URL,
            json={"metadata": {"ideType": "ANTIGRAVITY"}},
            headers=self._headers(ag.access_token),
            timeout=30.0,
        )
        if response.status_code != 200:
            return response
        load_data = response.json()
        project = _extract_project_id(load_data)
        if project:
            ag.project = project
            return project
        if not ag.auto_onboard:
            raise RuntimeError(
                "No Antigravity project returned by loadCodeAssist; set project explicitly "
                "or enable auto_onboard for an account you are authorized to modify"
            )

        payload = {
            "tier_id": _default_tier_id(load_data),
            "metadata": {
                "ide_type": "ANTIGRAVITY",
                "ide_name": "antigravity",
                "ide_version": ANTIGRAVITY_HEADERS["X-Client-Version"],
            },
        }
        for attempt in range(ONBOARD_ATTEMPTS):
            response = await client.post(
                ONBOARD_USER_URL,
                json=payload,
                headers=self._headers(ag.access_token),
                timeout=30.0,
            )
            if response.status_code != 200:
                return response
            data = response.json()
            if data.get("done"):
                project = _extract_project_id(data.get("response", {}))
                if not project:
                    raise RuntimeError("Antigravity onboarding completed without a project ID")
                ag.project = project
                return project
            if attempt + 1 < ONBOARD_ATTEMPTS:
                await asyncio.sleep(ONBOARD_POLL_SECONDS)
        raise RuntimeError(f"Antigravity onboarding did not complete after {ONBOARD_ATTEMPTS} attempts")

    async def forward(
        self,
        body: dict,
        cred: PooledCredential,
        stream: bool,
        client: httpx.AsyncClient,
    ) -> httpx.Response:
        await self.refresh_credential(cred)
        ag: AntigravityCredential = cred.credential  # type: ignore[attr-defined]

        model = _resolve_model_name(body.get("model", "gemini-3.7-flash").split("/")[-1])
        gemini_req = _openai_to_gemini(body)
        project = await self._ensure_project(ag, client)
        if isinstance(project, httpx.Response):
            return project

        payload = {
            "project": project,
            "model": model,
            "request": gemini_req,
            "userAgent": "antigravity",
            "requestType": "agent",
            "requestId": f"agent-{uuid.uuid4()}",
        }

        headers = self._headers(ag.access_token)

        path = "/v1internal:streamGenerateContent?alt=sse" if stream else "/v1internal:generateContent"
        last_error: Exception | None = None
        for index, endpoint in enumerate(ENDPOINTS):
            url = f"{endpoint}{path}"
            try:
                request = client.build_request(
                    "POST",
                    url,
                    json=payload,
                    headers=headers,
                    timeout=httpx.Timeout(120.0, connect=30.0),
                )
                resp = await client.send(request, stream=stream)
                if resp.status_code == 404 and index + 1 < len(ENDPOINTS):
                    logger.warning("Endpoint %s returned 404 for %s; trying fallback", endpoint, cred.id)
                    await resp.aclose()
                    continue
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
