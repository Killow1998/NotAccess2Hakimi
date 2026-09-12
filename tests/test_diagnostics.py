"""Privacy and bounds for the local diagnostic journal."""

from tests.platform_assertions import assert_storage_access

import json
import os
import pytest

from httpx2 import ASGITransport, AsyncClient

from hakimi_proxy.diagnostics import DiagnosticJournal
from hakimi_proxy.main import create_app


def test_journal_keeps_only_allowlisted_fields_and_private_modes(tmp_path):
    path = tmp_path / "private" / "diagnostics.jsonl"
    journal = DiagnosticJournal(path)
    journal.record(
        "http_request",
        method="POST",
        route="/v1/responses",
        status=200,
        duration_ms=12,
        authorization="Bearer secret",
        prompt="do not persist me",
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["route"] == "/v1/responses"
    assert "authorization" not in record
    assert "prompt" not in record
    assert "secret" not in path.read_text(encoding="utf-8")
    assert_storage_access(path)
    assert_storage_access(path.parent)


def test_journal_writes_without_fd_permission_support(tmp_path, monkeypatch):
    monkeypatch.delattr(os, "fchmod", raising=False)
    path = tmp_path / "diagnostics.jsonl"
    journal = DiagnosticJournal(path)

    journal.record("startup", version="0.6.1")

    assert journal.enabled is True
    assert json.loads(path.read_text(encoding="utf-8"))["event"] == "startup"
    assert_storage_access(path)


def test_journal_rotates_at_a_bounded_size(tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    journal = DiagnosticJournal(path, max_bytes=1024, backup_count=2)
    for _ in range(40):
        journal.record(
            "http_request",
            method="POST",
            route="/v1/responses",
            status=200,
            duration_ms=1,
        )

    assert path.exists()
    assert path.with_name("diagnostics.jsonl.1").exists()
    assert not path.with_name("diagnostics.jsonl.3").exists()


def test_journal_refuses_a_symlink_target(tmp_path):
    target = tmp_path / "target.jsonl"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "diagnostics.jsonl"
    try:
        link.symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symbolic links require Developer Mode or SeCreateSymbolicLinkPrivilege")
        raise

    journal = DiagnosticJournal(link)

    assert journal.enabled is False


async def test_http_journal_records_route_template_without_query(tmp_path):
    app = create_app()
    app.state.diagnostics = DiagnosticJournal(tmp_path / "diagnostics.jsonl")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/v1/models?code=oauth-secret")

    assert response.status_code == 200
    text = app.state.diagnostics.path.read_text(encoding="utf-8")
    record = json.loads(text)
    assert record["route"] == "/v1/models"
    assert "oauth-secret" not in text
    assert "code" not in text


async def test_emp_request_id_reaches_response_and_journal(tmp_path):
    app = create_app()
    app.state.diagnostics = DiagnosticJournal(tmp_path / "diagnostics.jsonl")
    request_id = "0123456789abcdef"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/v1/models", headers={"X-EMP-Request-ID": request_id})
    assert response.headers["X-Request-ID"] == request_id
    assert json.loads(app.state.diagnostics.path.read_text())["request_id"] == request_id
