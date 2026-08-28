"""Application entry-point behavior."""

import uvicorn

from hakimi_proxy.adapters import antigravity as antigravity_module
from hakimi_proxy.config import AntigravityCredential, ProxyConfig, load_config, save_config
from hakimi_proxy import main as main_module


def test_main_runs_prebuilt_app_without_implicit_reload(monkeypatch):
    captured = {}

    def fake_run(target, **kwargs):
        captured["target"] = target
        captured["kwargs"] = kwargs

    monkeypatch.setattr(uvicorn, "run", fake_run)
    main_module.main()

    assert captured["target"] is main_module.app
    assert captured["kwargs"]["host"] == main_module.app.state.config.host
    assert captured["kwargs"]["port"] == main_module.app.state.config.port
    assert "reload" not in captured["kwargs"]
    assert main_module.app.version == "0.4.0"


async def test_rotated_refresh_token_survives_application_restart(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    save_config(
        ProxyConfig(
            db_path=str(tmp_path / "usage.db"),
            antigravity_credentials=[AntigravityCredential(
                id="ag-restart",
                client_id="client-id",
                client_secret="client-secret",
                refresh_token="old-refresh",
            )],
        ),
        config_path,
    )
    monkeypatch.setenv("HAKIMI_CONFIG", str(config_path))

    class Response:
        status_code = 200

        def json(self):
            return {
                "access_token": "new-access",
                "refresh_token": "rotated-refresh",
                "expires_in": 3600,
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(antigravity_module.httpx, "AsyncClient", lambda **kwargs: Client())
    app = main_module.create_app()
    pooled = app.state.pool.all_credentials[0]

    await app.state.antigravity.refresh_credential(pooled)
    reloaded = load_config(config_path)

    assert reloaded.antigravity_credentials[0].refresh_token == "rotated-refresh"
    assert config_path.stat().st_mode & 0o777 == 0o600
