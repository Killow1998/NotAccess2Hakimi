"""Privacy and bounds for the local diagnostic journal."""

import json
import stat

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
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


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
    link.symlink_to(target)

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
