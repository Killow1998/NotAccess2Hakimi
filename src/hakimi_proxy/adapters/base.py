"""Abstract base for upstream adapters."""

from __future__ import annotations

import abc
import httpx

from hakimi_proxy.pool import PooledCredential


class UpstreamAdapter(abc.ABC):
    """Interface for upstream provider adapters."""

    def __init__(self, proxy: str = "") -> None:
        self.proxy = proxy

    @property
    @abc.abstractmethod
    def kind(self) -> str:
        """Return 'aistudio' or 'antigravity'."""

    @abc.abstractmethod
    def supports_model(self, model: str) -> bool:
        """Whether this adapter can serve the given model."""

    @abc.abstractmethod
    async def refresh_credential(self, cred: PooledCredential) -> None:
        """Refresh token if needed (no-op for AI Studio)."""

    @abc.abstractmethod
    async def forward(
        self,
        body: dict,
        cred: PooledCredential,
        stream: bool,
        client: httpx.AsyncClient,
    ) -> httpx.Response:
        """Make the upstream request, return the raw httpx Response.

        Caller checks status_code for failover decisions.
        """

    @abc.abstractmethod
    def extract_usage(self, response_body: dict) -> dict:
        """Extract an OpenAI-format usage dict from a non-streaming response."""

    @abc.abstractmethod
    def transform_stream_line(self, raw_line: str) -> tuple[str | None, dict | None]:
        """Transform one SSE line from the upstream.

        Returns (openai_sse_data_or_None, usage_dict_or_None).
        - For passthrough adapters, this parses and forwards the line as-is.
        - For transforming adapters, this converts to OpenAI SSE format.
        - Returns (None, None) for lines that should be skipped.
        """
