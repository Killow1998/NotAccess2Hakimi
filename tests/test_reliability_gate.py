"""Bounded, fake-upstream acceptance for the operational reliability gate."""

from hakimi_proxy.reliability_gate import run_gate


async def test_reliability_gate_exercises_public_success_and_fault_paths():
    result = await run_gate(requests=12, concurrency=4)

    assert result["status"] == "passed"
    assert result["requests"] == 12
    assert result["successes"] == 12
    assert result["max_active_upstream"] == 1
    assert result["leaked_leases"] == 0
    assert result["readiness_status"] == 200
    assert result["faults"] == {
        "rate_limit_failover": {"http_status": 200, "calls": 2},
        "upstream_503": {"http_status": 503, "error_type": "upstream_server_error"},
        "timeout": {"http_status": 503, "error_type": "upstream_transport_error"},
    }
