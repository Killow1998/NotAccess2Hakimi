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
    assert status["last_tested_at"] is None
    assert status["last_test_ok"] is None
@pytest.mark.parametrize("state", [CredentialState.COOLDOWN, CredentialState.DISABLED])
def test_reconfigure_preserves_health_and_runtime_credential(state):
    pool = CredentialPool()
    credential = _make_ag("same")
    pool.add_antigravity(credential)
    pooled = pool.all_credentials[0]
    pooled.state = state
    pooled.cooldown_until = time.time() + 100
    credential.access_token = "refreshed-token"
    credential.expires_at = 9999999999.0
    replacements = [_make_ag("same")]
    pool.reconfigure([], replacements, 120)
    assert pool.all_credentials[0] is pooled
    assert pooled.state is state
    assert replacements[0] is credential
    assert replacements[0].access_token == "refreshed-token"


@pytest.mark.asyncio
async def test_antigravity_parallel_generation_and_independent_quota():
    pool = CredentialPool()
    pool.add_antigravity(_make_ag("ag"))
    leases = [await pool.acquire(kind="antigravity") for _ in range(12)]
    quota = await pool.acquire(kind="antigravity", quota=True, timeout_seconds=0)
    assert quota.in_flight == 12
    with pytest.raises(CredentialUnavailable):
        await pool.acquire(kind="antigravity", quota=True, timeout_seconds=0)
    with pytest.raises(ValueError):
        pool.validate_reconfiguration([], [])
    await pool.release(quota, quota=True)
    for lease in leases:
        await pool.release(lease)
    assert quota.in_flight == quota.quota_in_flight == 0


@pytest.mark.asyncio
async def test_router_waits_for_cooling_account_and_quota_can_still_refresh():
    from hakimi_proxy.routes.chat import _acquire_for_request
    from hakimi_proxy.adapters.aistudio import AIStudioAdapter
    from hakimi_proxy.adapters.antigravity import AntigravityAdapter
    pool = CredentialPool()
    pool.add_antigravity(_make_ag("ag"))
    cred = pool.all_credentials[0]
    pool.mark_cooldown(cred, retry_after=0.05)
    quota = await pool.acquire(kind="antigravity", quota=True, timeout_seconds=0)
    await pool.release(quota, quota=True)
    ag = AntigravityAdapter()
    _, lease = await _acquire_for_request(pool, ag, AIStudioAdapter(), ag,
        "gemini-3.8-flash", time.monotonic() + 1)
    assert lease is cred
    await pool.release(lease)


def test_transient_failure_backoff_does_not_use_rate_limit_cooldown():
    from hakimi_proxy.routes.chat import _apply_failure, _failure_response
    from hakimi_proxy.errors import UpstreamFailure
    pool = CredentialPool(cooldown_seconds=60)
    pool.add_antigravity(_make_ag("ag"))
    cred = pool.all_credentials[0]
    failure = UpstreamFailure("upstream_server_error", "temporary", 503, True, "cooldown")
    _apply_failure(pool, cred, failure, "gemini", time.perf_counter())
    assert 0 < cred.cooldown_until - time.time() <= 2
    limited = UpstreamFailure("upstream_rate_limit", "limited", 429, True, "cooldown", 120)
    _apply_failure(pool, cred, limited, "gemini", time.perf_counter())
    assert 119 < cred.cooldown_until - time.time() <= 120
    assert _failure_response(limited, 503).headers["retry-after"] == "120"


@pytest.mark.asyncio
async def test_model_cooldown_does_not_block_other_models_or_quota():
    pool = CredentialPool()
    pool.add_antigravity(_make_ag("one"))
    cred = pool.all_credentials[0]
    pool.mark_cooldown(cred, 30, model="gemini-3.8-flash")
    with pytest.raises(CredentialUnavailable):
        await pool.acquire(model="gemini-3.8-flash", timeout_seconds=0)
    other = await pool.acquire(model="gemini-3.7-flash", timeout_seconds=0)
    await pool.release(other)
    quota = await pool.acquire(quota=True, timeout_seconds=0)
    await pool.release(quota, quota=True)
    pool.mark_cooldown(cred, 0, model="gemini-3.8-flash")
    recovered = await pool.acquire(model="gemini-3.8-flash", timeout_seconds=0)
    await pool.release(recovered)
    pool.mark_cooldown(cred, 30)
    with pytest.raises(CredentialUnavailable):
        await pool.acquire(model="gemini-3.7-flash", timeout_seconds=0)


def test_model_cooldown_requires_explicit_upstream_dimensions():
    import httpx
    from hakimi_proxy.errors import classify_response
    generic = classify_response(httpx.Response(429, json={"error": {"message": "model busy"}}))
    assert generic.cooldown_scope == "account"
    scoped = classify_response(httpx.Response(429, json={"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
            {"quotaDimensions": {"model": "gemini-3.8-flash", "location": "global"}}
        ]}
    ]}}))
    assert scoped.cooldown_scope == "model"
    server_error = classify_response(httpx.Response(503, json={"error": {"details": [{"metadata": {"model": "x"}}]}}))
    assert server_error.cooldown_scope == "account"


def test_mixed_quota_dimensions_keep_account_cooldown():
    import httpx
    from hakimi_proxy.errors import classify_response
    failure = classify_response(httpx.Response(429, json={"error": {"details": [{"violations": [
        {"quotaDimensions": {"model": "gemini-3.8-flash"}}, {"quotaDimensions": {"project": "fixture"}}
    ]}]}}))
    assert failure.cooldown_scope == "account"
