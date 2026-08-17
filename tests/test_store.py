"""Tests for the SQLite usage store."""

import tempfile
from pathlib import Path

from hakimi_proxy.metering.models import TokenBreakdown, UsageRecord
from hakimi_proxy.metering.store import UsageStore


def _make_record(cred_id="acct1", model="gemini-3.7-flash", upstream="aistudio", cost=0.001):
    return UsageRecord(
        credential_id=cred_id,
        model=model,
        upstream=upstream,
        tokens=TokenBreakdown(input=100, output=50),
        cost_usd=cost,
    )


def test_record_and_query():
    """Record usage and query it back."""
    with tempfile.TemporaryDirectory() as tmp:
        store = UsageStore(Path(tmp) / "test.db")
        store.record(_make_record())
        rows = store.get_usage()
        assert len(rows) == 1
        assert rows[0]["credential_id"] == "acct1"
        assert rows[0]["input_tokens"] == 100
        assert rows[0]["output_tokens"] == 50
        assert rows[0]["cost_usd"] == 0.001
        assert rows[0]["request_count"] == 1


def test_record_aggregation():
    """Multiple records on same day+cred+model are aggregated."""
    with tempfile.TemporaryDirectory() as tmp:
        store = UsageStore(Path(tmp) / "test.db")
        store.record(_make_record(cost=0.001))
        store.record(_make_record(cost=0.002))
        store.record(_make_record(cost=0.003))

        rows = store.get_usage()
        assert len(rows) == 1
        assert rows[0]["request_count"] == 3
        assert rows[0]["input_tokens"] == 300
        assert rows[0]["output_tokens"] == 150
        assert abs(rows[0]["cost_usd"] - 0.006) < 1e-10


def test_record_different_credentials():
    """Different credentials create separate rows."""
    with tempfile.TemporaryDirectory() as tmp:
        store = UsageStore(Path(tmp) / "test.db")
        store.record(_make_record(cred_id="a"))
        store.record(_make_record(cred_id="b"))

        rows = store.get_usage()
        assert len(rows) == 2


def test_filter_by_credential():
    with tempfile.TemporaryDirectory() as tmp:
        store = UsageStore(Path(tmp) / "test.db")
        store.record(_make_record(cred_id="a"))
        store.record(_make_record(cred_id="b"))

        rows = store.get_usage(credential_id="a")
        assert len(rows) == 1
        assert rows[0]["credential_id"] == "a"


def test_filter_by_model():
    with tempfile.TemporaryDirectory() as tmp:
        store = UsageStore(Path(tmp) / "test.db")
        store.record(_make_record(model="gemini-3.7-flash"))
        store.record(_make_record(model="gemini-2.0-flash"))

        rows = store.get_usage(model="gemini-3.7-flash")
        assert len(rows) == 1
        assert rows[0]["model"] == "gemini-3.7-flash"


def test_usage_log():
    """Individual log entries are stored separately from aggregates."""
    with tempfile.TemporaryDirectory() as tmp:
        store = UsageStore(Path(tmp) / "test.db")
        store.record(_make_record())
        store.record(_make_record())

        logs = store.get_usage_log()
        assert len(logs) == 2
        assert all("ts" in log for log in logs)


def test_compute_cost_integration():
    """Full flow: record with computed cost, verify in store."""
    from hakimi_proxy.metering.pricing import compute_cost_for_model

    with tempfile.TemporaryDirectory() as tmp:
        store = UsageStore(Path(tmp) / "test.db")
        tokens = TokenBreakdown(input=1000, output=500)
        cost = compute_cost_for_model("gemini-3.7-flash", tokens)
        rec = UsageRecord(
            credential_id="acct1",
            model="gemini-3.7-flash",
            upstream="aistudio",
            tokens=tokens,
            cost_usd=cost,
        )
        store.record(rec)

        rows = store.get_usage()
        assert len(rows) == 1
        expected_cost = (1000 * 0.75 + 500 * 3.75) / 1_000_000
        assert abs(rows[0]["cost_usd"] - expected_cost) < 1e-10
