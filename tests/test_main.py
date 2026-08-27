"""Application entry-point behavior."""

import uvicorn

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
    assert main_module.app.version == "0.3.0"
