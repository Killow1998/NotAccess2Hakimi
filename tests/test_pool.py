"""Tests for the credential pool state machine and LRU scheduling."""

import asyncio
import time

import pytest

from hakimi_proxy.config import AIStudioCredential, AntigravityCredential
from hakimi_proxy.pool import CredentialPool, CredentialState, CredentialUnavailable


def _make_ai(id: str) -> AIStudioCredential:
    return AIStudioCredential(id=id, api_key=f"key-{id}")


def _make_ag(id: str) -> AntigravityCredential:
    return AntigravityCredential(
        id=id, client_id="cid", client_secret="cs", refresh_token="rt"
    )


def test_single_credential_works():
    """Single-account mode: N=1 is a valid退化子集."""
    pool = CredentialPool()
    pool.add_aistudio(_make_ai("only"))
    cred = pool.get_available(kind="aistudio")
    assert cred is not None
    assert cred.id == "only"


def test_lru_scheduling():
    """Least-recently-used credential is selected first."""
    pool = CredentialPool()
    pool.add_aistudio(_make_ai("a"))
    pool.add_aistudio(_make_ai("b"))
    pool.add_aistudio(_make_ai("c"))

    first = pool.get_available(kind="aistudio")
    assert first is not None
    second = pool.get_available(kind="aistudio")
    assert second is not None
    third = pool.get_available(kind="aistudio")
    assert third is not None

    # All three should be different
    ids = {first.id, second.id, third.id}
    assert ids == {"a", "b", "c"}

    # Fourth call should reuse the LRU (which is 'first' since it was used earliest)
    fourth = pool.get_available(kind="aistudio")
    assert fourth is not None
    assert fourth.id == first.id


def test_cooldown_blocks_and_heals():
    """Cooldown prevents selection, then heals after timeout."""
    pool = CredentialPool(cooldown_seconds=1)
    pool.add_aistudio(_make_ai("a"))
    pool.add_aistudio(_make_ai("b"))

    # Use 'a', then put it in cooldown
    a = pool.get_available(kind="aistudio")
    assert a is not None
    pool.mark_cooldown(a, retry_after=1)
    assert a.state == CredentialState.COOLDOWN

    # 'b' should be selected now
    b = pool.get_available(kind="aistudio")
    assert b is not None
    assert b.id == "b"

    # Wait for cooldown to expire
    time.sleep(1.2)

    # 'a' should be available again (it's now LRU)
    healed = pool.get_available(kind="aistudio")
    assert healed is not None
    assert healed.id == "a"
    assert healed.state == CredentialState.ACTIVE


def test_disabled_permanent():
    """Disabled credentials are never selected."""
    pool = CredentialPool()
    pool.add_aistudio(_make_ai("a"))
    pool.add_aistudio(_make_ai("b"))

    a = pool.get_available(kind="aistudio")
    pool.mark_disabled(a)
    assert a.state == CredentialState.DISABLED

    # Only 'b' available
    for _ in range(5):
        cred = pool.get_available(kind="aistudio")
        assert cred is not None
        assert cred.id == "b"


def test_kind_filter():
    """get_available with kind filter only returns matching credentials."""
    pool = CredentialPool()
    pool.add_aistudio(_make_ai("ai1"))
    pool.add_antigravity(_make_ag("ag1"))

    ai = pool.get_available(kind="aistudio")
    assert ai is not None
    assert ai.id == "ai1"
    assert ai.kind == "aistudio"

    ag = pool.get_available(kind="antigravity")
    assert ag is not None
    assert ag.id == "ag1"
    assert ag.kind == "antigravity"


def test_all_cooldown_returns_none():
    """When all credentials are in cooldown, get_available returns None."""
    pool = CredentialPool(cooldown_seconds=60)
    pool.add_aistudio(_make_ai("a"))

    a = pool.get_available(kind="aistudio")
    pool.mark_cooldown(a, retry_after=60)

    assert pool.get_available(kind="aistudio") is None


def test_get_status():
    """get_status returns runtime info for all credentials."""
    pool = CredentialPool()
    pool.add_aistudio(_make_ai("a"))
    pool.add_antigravity(_make_ag("b"))

    status = pool.get_status()
    assert len(status) == 2
    ids = {s["id"] for s in status}
    assert ids == {"a", "b"}
    assert all(s["state"] == "active" for s in status)


def test_active_count():
    """get_active_count reflects current state."""
    pool = CredentialPool(cooldown_seconds=60)
    pool.add_aistudio(_make_ai("a"))
    pool.add_aistudio(_make_ai("b"))

    assert pool.get_active_count(kind="aistudio") == 2

    a = pool.get_available(kind="aistudio")
    pool.mark_cooldown(a, retry_after=60)

    assert pool.get_active_count(kind="aistudio") == 1
    assert pool.get_active_count(kind="antigravity") == 0


@pytest.mark.asyncio
async def test_single_flight_lease_waits_then_releases():
    pool = CredentialPool()
    pool.add_aistudio(_make_ai("only"))

    first = await pool.acquire(kind="aistudio")
    pending = asyncio.create_task(pool.acquire(kind="aistudio", timeout_seconds=0.2))
    await asyncio.sleep(0.01)
    assert not pending.done()

    await pool.release(first)
    second = await pending
    assert second.id == "only"
    assert second.in_flight == 1
    await pool.release(second)


@pytest.mark.asyncio
async def test_busy_lease_times_out_without_leaking():
    pool = CredentialPool()
    pool.add_aistudio(_make_ai("only"))
    first = await pool.acquire(kind="aistudio")

    with pytest.raises(CredentialUnavailable) as exc_info:
        await pool.acquire(kind="aistudio", timeout_seconds=0.01)

    assert exc_info.value.reason == "busy_timeout"
    assert first.in_flight == 1
    await pool.release(first)
    assert first.in_flight == 0


@pytest.mark.asyncio
async def test_concurrent_leases_use_different_credentials():
    pool = CredentialPool()
    pool.add_aistudio(_make_ai("a"))
    pool.add_aistudio(_make_ai("b"))

    first, second = await asyncio.gather(
        pool.acquire(kind="aistudio"),
        pool.acquire(kind="aistudio"),
    )
    assert {first.id, second.id} == {"a", "b"}
    await pool.release(first)
    await pool.release(second)


@pytest.mark.asyncio
async def test_status_exposes_runtime_health_fields():
    pool = CredentialPool()
    pool.add_aistudio(_make_ai("only"))
    lease = await pool.acquire(kind="aistudio")
    pool.mark_success(lease, latency_ms=12, model="gemini-3.7-flash")
    await pool.release(lease)

    status = pool.get_status()[0]
    assert status["in_flight"] == 0
    assert status["last_success_at"] is not None
    assert status["last_latency_ms"] == 12
    assert status["last_model"] == "gemini-3.7-flash"
