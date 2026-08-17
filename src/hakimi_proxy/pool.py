"""Credential pool with state machine and LRU scheduling."""

from __future__ import annotations

import enum
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
            remaining = max(0, pc.cooldown_until - now) if pc.state == CredentialState.COOLDOWN else 0
            result.append({
                "id": pc.id,
                "kind": pc.kind,
                "state": pc.state.value,
                "cooldown_remaining": round(remaining, 1),
                "failure_count": pc.failure_count,
                "last_used": pc.last_used,
            })
        return result
