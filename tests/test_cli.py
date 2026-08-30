"""Public CLI behavior."""

from __future__ import annotations

import json
import sys

import httpx
import pytest

from hakimi_proxy.config import (
    AIStudioCredential,
    AntigravityCredential,
    ProxyConfig,
    load_config,
    save_config,
)


def test_generate_key_prints_one_strong_api_key(capsys):
    from hakimi_proxy.cli import main

    exit_code = main(["generate-key"])

    generated = capsys.readouterr().out.strip()
    assert exit_code == 0
    assert generated.startswith("hakimi_")
    assert len(generated) >= 50
    assert generated.split() == [generated]


def test_doctor_reports_missing_config_with_next_action(tmp_path, capsys):
    from hakimi_proxy.cli import main

    config_path = tmp_path / "missing.yaml"

    exit_code = main(["doctor", "--config", str(config_path), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "setup_required"
    assert payload["config"] == {
        "path": str(config_path.resolve()),
        "exists": False,
    }
    assert payload["checks"][0]["name"] == "config_file"
    assert payload["checks"][0]["status"] == "error"
    assert payload["next_actions"] == [
        f"Run hakimi serve --config {config_path.resolve()}, copy the generated "
        "deployment key from that terminal, then open http://127.0.0.1:12345 and log in"
    ]


def test_doctor_redacts_config_and_explains_incomplete_setup(tmp_path, capsys, monkeypatch):
    from hakimi_proxy import cli

    config_path = tmp_path / "config.yaml"
    save_config(
        ProxyConfig(
            port=18000,
            auth_token="downstream-secret",
            proxy="socks5://proxy-user:proxy-secret@127.0.0.1:1080",
        ),
        config_path,
    )

    class OfflineClient:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            raise httpx.ConnectError("downstream-secret proxy-secret")

    monkeypatch.setattr(cli.httpx, "Client", OfflineClient)

    exit_code = cli.main(["doctor", "--config", str(config_path), "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["status"] == "setup_required"
    assert payload["config"]["credential_counts"] == {
        "aistudio": 0,
        "antigravity": 0,
        "total": 0,
    }
    assert payload["config"]["auth_enabled"] is True
    assert payload["config"]["proxy_source"] == "config"
    assert payload["service"] == {
        "base_url": "http://127.0.0.1:18000",
        "running": False,
    }
    checks = {item["name"]: item["status"] for item in payload["checks"]}
    assert checks == {
        "config_file": "ok",
        "credentials": "error",
        "service": "warning",
    }
    assert any("hakimi serve" in action for action in payload["next_actions"])
    assert any("add a credential" in action for action in payload["next_actions"])
    assert "downstream-secret" not in output
    assert "proxy-secret" not in output


def test_doctor_requires_matching_ready_service(tmp_path, capsys, monkeypatch):
    from hakimi_proxy import cli

    config_path = tmp_path / "config.yaml"
    save_config(
        ProxyConfig(
            port=18001,
            aistudio_credentials=[AIStudioCredential(id="primary", api_key="secret-key")],
        ),
        config_path,
    )

    class ReadyClient:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            request = httpx.Request("GET", url)
            if url.endswith("/openapi.json"):
                return httpx.Response(200, request=request, json={
                    "info": {"version": cli.__version__},
                })
            assert url.endswith("/readyz")
            return httpx.Response(200, request=request, json={
                "status": "ready",
                "active_credentials": 1,
                "total_credentials": 1,
                "in_flight_requests": 0,
            })

    monkeypatch.setattr(cli.httpx, "Client", ReadyClient)

    exit_code = cli.main(["doctor", "--config", str(config_path), "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["status"] == "ready"
    assert payload["service"] == {
        "base_url": "http://127.0.0.1:18001",
        "running": True,
        "version": cli.__version__,
        "ready": True,
        "active_credentials": 1,
        "total_credentials": 1,
    }
    checks = {item["name"]: item["status"] for item in payload["checks"]}
    assert checks == {
        "config_file": "ok",
        "credentials": "ok",
        "service": "ok",
        "version": "ok",
        "readiness": "ok",
    }
    assert payload["next_actions"] == []
    assert "secret-key" not in output


def test_serve_selects_config_before_importing_application(tmp_path, monkeypatch):
    from hakimi_proxy import cli

    config_path = tmp_path / "config.yaml"
    save_config(
        ProxyConfig(port=18002, db_path=str(tmp_path / "usage.db")),
        config_path,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HAKIMI_CONFIG", "")
    monkeypatch.setenv("HAKIMI_DIAGNOSTICS_PATH", str(tmp_path / "diagnostics.jsonl"))
    sys.modules.pop("hakimi_proxy.main", None)
    captured = {}

    def fake_run(target, **kwargs):
        captured["target"] = target
        captured["kwargs"] = kwargs

    monkeypatch.setattr("uvicorn.run", fake_run)

    exit_code = cli.main(["serve", "--config", str(config_path)])

    assert exit_code == 0
    assert captured["target"].state.config.port == 18002
    assert captured["kwargs"]["port"] == 18002
    assert captured["kwargs"]["host"] == "127.0.0.1"
    assert cli.os.environ["HAKIMI_CONFIG"] == str(config_path.resolve())


def test_serve_provisions_missing_key_before_non_loopback_start(tmp_path, capsys, monkeypatch):
    from hakimi_proxy import cli

    config_path = tmp_path / "config.yaml"
    save_config(ProxyConfig(host="0.0.0.0", auth_token=""), config_path)
    monkeypatch.setenv("HAKIMI_CONFIG", "")
    started = []
    fake_module = type("MainModule", (), {"main": lambda: started.append(True)})
    monkeypatch.setattr(cli.importlib, "import_module", lambda _name: fake_module)

    exit_code = cli.main(["serve", "--config", str(config_path)])

    persisted = load_config(config_path)
    output = capsys.readouterr().err
    assert exit_code == 0
    assert started == [True]
    assert persisted.auth_token.startswith("hakimi_")
    assert len(persisted.auth_token) >= 50
    assert persisted.auth_token in output
    assert "generated deployment API key" in output
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_serve_creates_missing_config_with_initial_key(tmp_path, capsys, monkeypatch):
    from hakimi_proxy import cli

    config_path = tmp_path / "new-config.yaml"
    monkeypatch.setenv("HAKIMI_CONFIG", "")
    started = []
    fake_module = type("MainModule", (), {"main": lambda: started.append(True)})
    monkeypatch.setattr(cli.importlib, "import_module", lambda _name: fake_module)

    exit_code = cli.main(["serve", "--config", str(config_path)])

    persisted = load_config(config_path)
    output = capsys.readouterr().err
    assert exit_code == 0
    assert started == [True]
    assert persisted.auth_token.startswith("hakimi_")
    assert persisted.auth_token in output
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_serve_reuses_existing_key_without_printing_it(tmp_path, capsys, monkeypatch):
    from hakimi_proxy import cli

    config_path = tmp_path / "config.yaml"
    save_config(
        ProxyConfig(host="0.0.0.0", auth_token="operator-chosen-key"),
        config_path,
    )
    monkeypatch.setenv("HAKIMI_CONFIG", "")
    started = []
    fake_module = type("MainModule", (), {"main": lambda: started.append(True)})
    monkeypatch.setattr(cli.importlib, "import_module", lambda _name: fake_module)

    exit_code = cli.main(["serve", "--config", str(config_path)])

    assert exit_code == 0
    assert started == [True]
    output = capsys.readouterr().err
    assert "operator-chosen-key" not in output
    assert "generated deployment API key" not in output


def test_serve_fails_closed_when_initial_key_cannot_be_saved(tmp_path, capsys, monkeypatch):
    from hakimi_proxy import cli

    config_path = tmp_path / "missing-parent" / "config.yaml"
    monkeypatch.setenv("HAKIMI_CONFIG", "")
    monkeypatch.setattr(
        cli.importlib,
        "import_module",
        lambda _name: pytest.fail("application imported after key persistence failure"),
    )

    exit_code = cli.main(["serve", "--config", str(config_path)])

    assert exit_code == 2
    assert not config_path.exists()
    output = capsys.readouterr().err
    assert "could not save the generated deployment key" in output
    assert str(config_path) in output


def test_doctor_live_reuses_layered_health_for_single_account(tmp_path, capsys, monkeypatch):
    from hakimi_proxy import cli

    config_path = tmp_path / "config.yaml"
    save_config(
        ProxyConfig(
            port=18003,
            auth_token="local-bearer-secret",
            antigravity_credentials=[AntigravityCredential(
                id="agy-main",
                client_id="client-secret-id",
                client_secret="oauth-client-secret",
                refresh_token="oauth-refresh-secret",
            )],
        ),
        config_path,
    )
    posts = []

    class LiveClient:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, **kwargs):
            request = httpx.Request("GET", url)
            if url.endswith("/openapi.json"):
                return httpx.Response(200, request=request, json={
                    "info": {"version": cli.__version__},
                })
            if url.endswith("/readyz"):
                return httpx.Response(200, request=request, json={
                    "status": "ready",
                    "active_credentials": 1,
                    "total_credentials": 1,
                })
            assert url.endswith("/api/credentials")
            assert kwargs["headers"]["Authorization"] == "Bearer local-bearer-secret"
            return httpx.Response(200, request=request, json={
                "aistudio": [],
                "antigravity": [{"id": "agy-main", "kind": "antigravity"}],
            })

        def post(self, url, **kwargs):
            posts.append(url)
            assert url.endswith("/api/credentials/antigravity/agy-main/test")
            assert kwargs["headers"]["Authorization"] == "Bearer local-bearer-secret"
            request = httpx.Request("POST", url)
            return httpx.Response(200, request=request, json={
                "status": "ok",
                "credential_id": "agy-main",
                "provider": "antigravity",
                "model": "antigravity/gemini-3.7-flash-tiered",
                "latency_ms": 123,
                "health": {
                    "status": "healthy",
                    "stages": [
                        {"name": "local", "status": "ok", "latency_ms": 0},
                        {"name": "oauth", "status": "ok", "latency_ms": 10},
                        {"name": "control_plane", "status": "ok", "latency_ms": 20},
                        {"name": "inference", "status": "ok", "latency_ms": 93},
                    ],
                },
            })

    monkeypatch.setattr(cli.httpx, "Client", LiveClient)

    exit_code = cli.main([
        "doctor", "--config", str(config_path), "--live", "--json",
    ])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["status"] == "healthy"
    assert payload["live"] == {
        "status": "healthy",
        "provider": "antigravity",
        "credential_id": "agy-main",
        "model": "antigravity/gemini-3.7-flash-tiered",
        "latency_ms": 123,
        "stages": [
            {"name": "local", "status": "ok", "latency_ms": 0},
            {"name": "oauth", "status": "ok", "latency_ms": 10},
            {"name": "control_plane", "status": "ok", "latency_ms": 20},
            {"name": "inference", "status": "ok", "latency_ms": 93},
        ],
    }
    assert posts == ["http://127.0.0.1:18003/api/credentials/antigravity/agy-main/test"]
    assert {item["name"]: item["status"] for item in payload["checks"]}["live_credential"] == "ok"
    for secret in (
        "local-bearer-secret",
        "client-secret-id",
        "oauth-client-secret",
        "oauth-refresh-secret",
    ):
        assert secret not in output


def test_doctor_live_requires_selection_for_multiple_accounts(tmp_path, capsys, monkeypatch):
    from hakimi_proxy import cli

    config_path = tmp_path / "config.yaml"
    save_config(
        ProxyConfig(
            port=18004,
            aistudio_credentials=[AIStudioCredential(id="ai-main", api_key="ai-secret")],
            antigravity_credentials=[AntigravityCredential(
                id="agy-main",
                client_id="client-id",
                client_secret="client-secret",
                refresh_token="refresh-secret",
            )],
        ),
        config_path,
    )

    class MultipleClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, **kwargs):
            request = httpx.Request("GET", url)
            if url.endswith("/openapi.json"):
                return httpx.Response(200, request=request, json={
                    "info": {"version": cli.__version__},
                })
            if url.endswith("/readyz"):
                return httpx.Response(200, request=request, json={
                    "status": "ready",
                    "active_credentials": 2,
                    "total_credentials": 2,
                })
            return httpx.Response(200, request=request, json={
                "aistudio": [{"id": "ai-main", "kind": "aistudio"}],
                "antigravity": [{"id": "agy-main", "kind": "antigravity"}],
            })

        def post(self, url, **kwargs):
            raise AssertionError("doctor must not choose one of multiple accounts")

    monkeypatch.setattr(cli.httpx, "Client", MultipleClient)

    exit_code = cli.main([
        "doctor", "--config", str(config_path), "--live", "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "selection_required"
    assert payload["live"] == {
        "status": "selection_required",
        "candidates": [
            {"provider": "aistudio", "credential_id": "ai-main"},
            {"provider": "antigravity", "credential_id": "agy-main"},
        ],
    }
    assert payload["next_actions"][:2] == [
        f"Run hakimi doctor --config {config_path.resolve()} --live "
        "--credential aistudio:ai-main",
        f"Run hakimi doctor --config {config_path.resolve()} --live "
        "--credential antigravity:agy-main",
    ]


def test_doctor_live_accepts_explicit_provider_and_credential(tmp_path, capsys, monkeypatch):
    from hakimi_proxy import cli

    config_path = tmp_path / "config.yaml"
    save_config(
        ProxyConfig(
            port=18005,
            aistudio_credentials=[AIStudioCredential(id="ai-main", api_key="ai-secret")],
            antigravity_credentials=[AntigravityCredential(
                id="agy-main",
                client_id="client-id",
                client_secret="client-secret",
                refresh_token="refresh-secret",
            )],
        ),
        config_path,
    )

    class SelectedClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, **kwargs):
            request = httpx.Request("GET", url)
            if url.endswith("/openapi.json"):
                return httpx.Response(200, request=request, json={
                    "info": {"version": cli.__version__},
                })
            if url.endswith("/readyz"):
                return httpx.Response(200, request=request, json={
                    "status": "ready",
                    "active_credentials": 2,
                    "total_credentials": 2,
                })
            return httpx.Response(200, request=request, json={
                "aistudio": [{"id": "ai-main", "kind": "aistudio"}],
                "antigravity": [{"id": "agy-main", "kind": "antigravity"}],
            })

        def post(self, url, **kwargs):
            assert url.endswith("/api/credentials/antigravity/agy-main/test")
            request = httpx.Request("POST", url)
            return httpx.Response(200, request=request, json={
                "status": "ok",
                "credential_id": "agy-main",
                "provider": "antigravity",
                "model": "antigravity/gemini-3.7-flash-tiered",
                "latency_ms": 55,
                "health": {"status": "healthy", "stages": []},
            })

    monkeypatch.setattr(cli.httpx, "Client", SelectedClient)

    exit_code = cli.main([
        "doctor",
        "--config", str(config_path),
        "--live",
        "--credential", "antigravity:agy-main",
        "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "healthy"
    assert payload["live"]["provider"] == "antigravity"
    assert payload["live"]["credential_id"] == "agy-main"


def test_verify_writes_private_redacted_report(tmp_path, capsys, monkeypatch):
    from hakimi_proxy import cli

    config_path = tmp_path / "config.yaml"
    report_path = tmp_path / "verification.json"
    save_config(
        ProxyConfig(
            port=18006,
            auth_token="local-bearer-secret",
            antigravity_credentials=[AntigravityCredential(
                id="private-account@example.com",
                client_id="client-private",
                client_secret="secret-private",
                refresh_token="refresh-private",
            )],
        ),
        config_path,
    )
    report = {
        "schema_version": 1,
        "fingerprint_version": 1,
        "status": "passed",
        "provider": "antigravity",
        "model": "antigravity/gemini-3.7-flash-tiered",
        "credential_ref": "sha256:0123456789abcdef",
        "generated_at": "2026-08-29T00:00:00+00:00",
        "stages": [],
        "summary": {"inference_requests": 3, "leaked_leases": 0, "duration_ms": 1},
    }

    class VerifyClient:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, **kwargs):
            assert url.endswith("/api/credentials")
            assert kwargs["headers"]["Authorization"] == "Bearer local-bearer-secret"
            return httpx.Response(200, request=httpx.Request("GET", url), json={
                "aistudio": [],
                "antigravity": [{"id": "private-account@example.com"}],
            })

        def post(self, url, **kwargs):
            assert url.endswith(
                "/api/credentials/antigravity/private-account%40example.com/verify"
            )
            return httpx.Response(200, request=httpx.Request("POST", url), json=report)

    monkeypatch.setattr(cli.httpx, "Client", VerifyClient)

    exit_code = cli.main([
        "verify",
        "--config", str(config_path),
        "--json",
        "--output", str(report_path),
    ])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == report
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    assert report_path.stat().st_mode & 0o777 == 0o600
    serialized = report_path.read_text(encoding="utf-8")
    for secret in (
        "private-account@example.com",
        "local-bearer-secret",
        "client-private",
        "secret-private",
        "refresh-private",
    ):
        assert secret not in serialized


def test_verify_replays_saved_report_without_network(tmp_path, capsys, monkeypatch):
    from hakimi_proxy import cli

    report_path = tmp_path / "verification.json"
    report_path.write_text(json.dumps({
        "schema_version": 1,
        "fingerprint_version": 1,
        "status": "failed",
        "provider": "antigravity",
        "model": "antigravity/gemini-3.7-flash-tiered",
        "credential_ref": "sha256:0123456789abcdef",
        "generated_at": "2026-08-29T00:00:00+00:00",
        "stages": [{"name": "local", "status": "passed", "latency_ms": 0}],
        "summary": {"inference_requests": 0, "leaked_leases": 0, "duration_ms": 0},
    }), encoding="utf-8")

    class NoNetwork:
        def __init__(self, **kwargs):
            raise AssertionError("offline replay must not construct an HTTP client")

    monkeypatch.setattr(cli.httpx, "Client", NoNetwork)

    exit_code = cli.main(["verify", "--replay", str(report_path), "--json"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "valid",
        "report_status": "failed",
        "schema_version": 1,
        "fingerprint_version": 1,
        "stage_count": 1,
    }
