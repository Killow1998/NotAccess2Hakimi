"""AI Studio adapter: passthrough to Google's OpenAI-compatible endpoint.

Endpoint: https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
No protocol conversion needed -- Google already speaks OpenAI format here.
"""

from __future__ import annotations

import json
import logging

import httpx

from hakimi_proxy.adapters.base import UpstreamAdapter
from hakimi_proxy.config import AIStudioCredential
from hakimi_proxy.pool import PooledCredential

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

# Models that the AI Studio free tier can serve
SUPPORTED_MODELS: set[str] = {
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-pro-preview",
    "gemini-3.6-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
}


class AIStudioAdapter(UpstreamAdapter):
    @property
    def kind(self) -> str:
        return "aistudio"

    def supports_model(self, model: str) -> bool:
        stripped = model.split("/")[-1]
        return stripped in SUPPORTED_MODELS or model in SUPPORTED_MODELS

    async def refresh_credential(self, cred: PooledCredential) -> None:
        pass  # API keys don't expire

    async def forward(
        self,
        body: dict,
        cred: PooledCredential,
        stream: bool,
        client: httpx.AsyncClient,
    ) -> httpx.Response:
        api_key = cred.credential.api_key  # type: ignore[attr-defined]
        url = f"{BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Ensure we get usage in streaming mode
        if stream:
            body.setdefault("stream_options", {})
            body["stream_options"].setdefault("include_usage", True)

        return await client.post(
            url,
            json=body,
            headers=headers,
            timeout=httpx.Timeout(120.0, connect=30.0),
        )

    def extract_usage(self, response_body: dict) -> dict:
        return response_body.get("usage", {})

    def transform_stream_line(self, raw_line: str) -> tuple[str | None, dict | None]:
        """Passthrough: the upstream already speaks OpenAI SSE."""
        if not raw_line.startswith("data:"):
            return None, None
        data_str = raw_line[5:].strip()
        if not data_str or data_str == "[DONE]":
            if data_str == "[DONE]":
                return raw_line, None
            return None, None
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            return None, None

        # Capture usage if present (typically in the final chunk)
        usage = chunk.get("usage")
        return raw_line, usage
