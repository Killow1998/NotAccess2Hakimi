"""Credential pool with state machine and LRU scheduling."""

from __future__ import annotations

import enum
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from hakimi_proxy.config import AIStudioCredential, AntigravityCredential

logger = logging.getLogger(__name__)


class CredentialState(enum.Enum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    DISABLED = "disabled"


T = TypeVar("T", AIStudioCredential, AntigravityCredential)


@dataclass
class PooledCredential(Generic[T]):
    """Wraps a config credential with runtime state."""

    credential: T
    state: CredentialState = CredentialState.ACTIVE
    last_used: float = 0.0
    cooldown_until: float = 0.0
    failure_count: int = 0
    in_flight: int = 0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    last_error_type: str = ""
    last_error_message: str = ""
    last_latency_ms: int = 0
    last_model: str = ""

    @property
    def id(self) -> str:
        return self.credential.id

    @property
    def kind(self) -> str:
        if isinstance(self.credential, AIStudioCredential):
            return "aistudio"
        return "antigravity"


class CredentialPool:
    """Manages a pool of credentials with LRU scheduling and failover.

    Supports any number of credentials (N=1 for single-account mode).
    Credentials are selected by least-recently-used, skipping cooldown/disabled.
    """

    def __init__(self, cooldown_seconds: int = 60) -> None:
        self._credentials: list[PooledCredential] = []
        self._cooldown_seconds = cooldown_seconds
        self._condition = asyncio.Condition()

    def add_aistudio(self, cred: AIStudioCredential) -> None:
        self._credentials.append(PooledCredential(credential=cred))

    def add_antigravity(self, cred: AntigravityCredential) -> None:
        self._credentials.append(PooledCredential(credential=cred))

    @property
    def all_credentials(self) -> list[PooledCredential]:
        return list(self._credentials)

    def get_available(self, kind: str | None = None) -> PooledCredential | None:
        """Get the least-recently-used active credential, optionally filtered by kind.

        Also heals credentials whose cooldown has expired.
        """
        now = time.time()
        candidates: list[PooledCredential] = []
        for pc in self._credentials:
            # Heal cooldown
            if pc.state == CredentialState.COOLDOWN and now >= pc.cooldown_until:
                pc.state = CredentialState.ACTIVE
                pc.failure_count = 0
                logger.info("Credential %s recovered from cooldown", pc.id)

            if pc.state != CredentialState.ACTIVE:
                continue
            if kind and pc.kind != kind:
                continue
            candidates.append(pc)

        if not candidates:
            return None

        # LRU: pick the one with the smallest last_used
        chosen = min(candidates, key=lambda c: c.last_used)
        chosen.last_used = now
        return chosen

    async def acquire(
        self,
        kind: str | None = None,
        *,
        credential_id: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> PooledCredential:
        """Lease one idle active credential, waiting up to ``timeout_seconds``."""
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            async with self._condition:
                now = time.time()
                active_exists = False
                matched = False
                next_cooldown: float | None = None
                candidates: list[PooledCredential] = []
                for pc in self._credentials:
                    if credential_id and pc.id != credential_id:
                        continue
                    if kind and pc.kind != kind:
                        continue
                    matched = True
                    if pc.state == CredentialState.COOLDOWN:
                        if now >= pc.cooldown_until:
                            pc.state = CredentialState.ACTIVE
                            pc.failure_count = 0
                            logger.info("Credential %s recovered from cooldown", pc.id)
                        else:
                            next_cooldown = min(next_cooldown or pc.cooldown_until, pc.cooldown_until)
                            continue
                    if pc.state != CredentialState.ACTIVE:
                        continue
                    active_exists = True
                    if pc.in_flight == 0:
                        candidates.append(pc)

                if candidates:
                    chosen = min(candidates, key=lambda c: c.last_used)
                    chosen.last_used = now
                    chosen.in_flight = 1
                    return chosen

                remaining = deadline - time.monotonic()
                if not matched or (not active_exists and next_cooldown is None):
                    raise CredentialUnavailable("unavailable")
                if remaining <= 0:
                    reason = "busy_timeout" if active_exists else "unavailable"
                    raise CredentialUnavailable(reason)
                if next_cooldown is not None:
                    remaining = min(remaining, max(0.0, next_cooldown - now))
                if remaining <= 0:
                    continue
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    continue

    async def release(self, pc: PooledCredential) -> None:
        """Release a lease and wake waiting callers."""
        async with self._condition:
            if pc.in_flight > 0:
                pc.in_flight -= 1
            else:
                logger.warning("Credential %s released without an active lease", pc.id)
            self._condition.notify_all()

    def mark_success(self, pc: PooledCredential, *, latency_ms: int, model: str = "") -> None:
        pc.last_success_at = time.time()
        pc.last_latency_ms = max(0, int(latency_ms))
        pc.last_error_type = ""
        pc.last_error_message = ""
        if model:
            pc.last_model = model

    def mark_failure(
        self,
        pc: PooledCredential,
        error_type: str,
        message: str,
        *,
        latency_ms: int = 0,
        model: str = "",
    ) -> None:
        pc.last_failure_at = time.time()
        pc.last_latency_ms = max(0, int(latency_ms))
        pc.last_error_type = error_type
        pc.last_error_message = message[:240]
        if model:
            pc.last_model = model

    def mark_cooldown(self, pc: PooledCredential, retry_after: int | None = None) -> None:
        """Put a credential into cooldown (429 / rate limit)."""
        duration = retry_after or self._cooldown_seconds
        pc.state = CredentialState.COOLDOWN
        pc.cooldown_until = time.time() + duration
        pc.failure_count += 1
        logger.warning(
            "Credential %s entering cooldown for %ds (failure #%d)",
            pc.id, duration, pc.failure_count,
        )

    def mark_disabled(self, pc: PooledCredential) -> None:
        """Permanently disable a credential (401 / 403)."""
        pc.state = CredentialState.DISABLED
        logger.error("Credential %s disabled (auth failure)", pc.id)

    def get_active_count(self, kind: str | None = None) -> int:
        now = time.time()
        count = 0
        for pc in self._credentials:
            if pc.state == CredentialState.COOLDOWN and now >= pc.cooldown_until:
                pc.state = CredentialState.ACTIVE
                pc.failure_count = 0
            if pc.state != CredentialState.ACTIVE:
                continue
            if kind and pc.kind != kind:
                continue
            count += 1
        return count

    def get_status(self) -> list[dict]:
        """Return status of all credentials for monitoring."""
        now = time.time()
        result = []
        for pc in self._credentials:
            if pc.state == CredentialState.COOLDOWN and now >= pc.cooldown_until:
                pc.state = CredentialState.ACTIVE
                pc.failure_count = 0
                logger.info("Credential %s recovered from cooldown", pc.id)
            remaining = max(0, pc.cooldown_until - now) if pc.state == CredentialState.COOLDOWN else 0
            result.append({
                "id": pc.id,
                "kind": pc.kind,
                "state": pc.state.value,
                "cooldown_remaining": round(remaining, 1),
                "failure_count": pc.failure_count,
                "last_used": pc.last_used,
                "in_flight": pc.in_flight,
                "last_success_at": pc.last_success_at or None,
                "last_failure_at": pc.last_failure_at or None,
                "last_error_type": pc.last_error_type or None,
                "last_error_message": pc.last_error_message or None,
                "last_latency_ms": pc.last_latency_ms or None,
                "last_model": pc.last_model or None,
            })
        return result


class CredentialUnavailable(RuntimeError):
    """No credential can be leased within the requested wait window."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
