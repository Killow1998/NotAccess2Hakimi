"""Shared upstream failure classification and safe error rendering."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class UpstreamFailure:
    """A provider failure reduced to safe, retryable runtime metadata."""

    type: str
    message: str
    upstream_status: int | None = None
    retryable: bool = False
    credential_action: str = "none"  # none | cooldown | disable
    retry_after: int | None = None
    quota_reset_at: str | None = None

    def public(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "type": self.type,
            "message": self.message,
        }
        if self.upstream_status is not None:
            detail["upstream_status"] = self.upstream_status
        if self.retry_after is not None:
            detail["retry_after"] = self.retry_after
        if self.quota_reset_at:
            detail["quota_reset_at"] = self.quota_reset_at
        return detail


class UpstreamError(RuntimeError):
    """Adapter-raised failure with an already classified cause."""

    def __init__(self, failure: UpstreamFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


def _seconds(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return max(0, math.ceil(float(value)))
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if not value:
        return None
    try:
        if value.endswith("ms"):
            return max(0, math.ceil(float(value[:-2]) / 1000))
        if value.endswith("s"):
            return max(0, math.ceil(float(value[:-1])))
        return max(0, math.ceil(float(value)))
    except ValueError:
        return None


def _payload_error(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    error = payload.get("error", payload)
    return error if isinstance(error, dict) else {}


def classify_response(response: httpx.Response) -> UpstreamFailure:
    """Classify an HTTP response without returning its raw body."""
    payload: Any = {}
    try:
        payload = response.json()
    except (ValueError, TypeError):
        pass
    error = _payload_error(payload)
    status = response.status_code
    provider_status = str(error.get("status") or "").strip()
    message = str(error.get("message") or "").strip()
    message = re.sub(r"\s+", " ", message)[:240]
    safe_message = (
        f"{provider_status}: {message}"
        if provider_status and message
        else message or f"Upstream returned HTTP {status}"
    )

    retry_after = _seconds(response.headers.get("retry-after"))
    quota_reset_at: str | None = None
    reason = ""
    for item in error.get("details", []):
        if not isinstance(item, dict):
            continue
        reason = reason or str(item.get("reason") or "").strip().upper()
        if retry_after is None:
            retry_after = _seconds(item.get("retryDelay"))
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            if retry_after is None:
                retry_after = _seconds(metadata.get("quotaResetDelay"))
            if metadata.get("quotaResetTimeStamp"):
                quota_reset_at = str(metadata["quotaResetTimeStamp"])

    if status in (401, 403):
        return UpstreamFailure(
            "upstream_auth_error", safe_message, status, False, "disable", retry_after, quota_reset_at
        )
    if status == 429:
        return UpstreamFailure(
            "upstream_rate_limit", safe_message, status, True, "cooldown", retry_after, quota_reset_at
        )
    if status >= 500:
        return UpstreamFailure(
            "upstream_server_error", safe_message, status, True, "cooldown", retry_after, quota_reset_at
        )
    if 400 <= status < 500:
        return UpstreamFailure("upstream_request_error", safe_message, status, False, "none", retry_after, quota_reset_at)
    if reason == "RATE_LIMIT_EXCEEDED":
        return UpstreamFailure(
            "upstream_rate_limit", safe_message, status, True, "cooldown", retry_after, quota_reset_at
        )
    return UpstreamFailure("upstream_error", safe_message, status, False, "none", retry_after, quota_reset_at)


def classify_exception(exc: BaseException) -> UpstreamFailure:
    """Classify adapter exceptions while keeping programming errors visible."""
    if isinstance(exc, UpstreamError):
        return exc.failure
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return UpstreamFailure("upstream_transport_error", f"{type(exc).__name__}: upstream connection failed", None, True, "cooldown")
    return UpstreamFailure("proxy_error", f"{type(exc).__name__}: upstream request failed", None, False, "none")
