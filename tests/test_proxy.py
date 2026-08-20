"""Tests for proxy source selection and environment setup."""

from hakimi_proxy import proxy


def _clear_proxy_environment(monkeypatch):
    for key in proxy.PROXY_ENV_KEYS + ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(key, raising=False)


def test_explicit_config_proxy_wins(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://environment:8080")
    monkeypatch.setattr(proxy, "_gnome_proxy_settings", lambda: {"https": "http://gnome:8080"})

    assert proxy.configure_proxy_environment("http://configured:8080") == "config"
    assert proxy.os.environ["HTTPS_PROXY"] == "http://environment:8080"


def test_environment_proxy_wins_when_config_empty(monkeypatch):
    _clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://environment:8080")
    monkeypatch.setattr(proxy, "getproxies", lambda: {"https": "http://system:8080"})
    monkeypatch.setattr(proxy, "_gnome_proxy_settings", lambda: {"https": "http://gnome:8080"})

    assert proxy.configure_proxy_environment() == "environment"
    assert proxy.os.environ["HTTPS_PROXY"] == "http://environment:8080"


def test_system_proxy_is_exported_when_config_and_environment_empty(monkeypatch):
    _clear_proxy_environment(monkeypatch)
    monkeypatch.setattr(proxy, "getproxies", lambda: {"https": "http://system:8080", "no": "localhost"})
    monkeypatch.setattr(proxy, "_gnome_proxy_settings", lambda: {})

    assert proxy.configure_proxy_environment() == "system"
    assert proxy.os.environ["HTTPS_PROXY"] == "http://system:8080"
    assert proxy.os.environ["https_proxy"] == "http://system:8080"
    assert proxy.os.environ["NO_PROXY"] == "localhost"


def test_gnome_proxy_is_exported_as_system_source(monkeypatch):
    _clear_proxy_environment(monkeypatch)
    monkeypatch.setattr(proxy, "getproxies", lambda: {})
    monkeypatch.setattr(proxy, "_gnome_proxy_settings", lambda: {
        "https": "http://gnome:8080",
        "all": "socks5://gnome:1080",
    })

    assert proxy.configure_proxy_environment() == "system"
    assert proxy.os.environ["HTTPS_PROXY"] == "http://gnome:8080"
    assert proxy.os.environ["ALL_PROXY"] == "socks5://gnome:1080"


def test_direct_source_when_no_proxy_is_available(monkeypatch):
    _clear_proxy_environment(monkeypatch)
    monkeypatch.setattr(proxy, "getproxies", lambda: {})
    monkeypatch.setattr(proxy, "_gnome_proxy_settings", lambda: {})

    assert proxy.configure_proxy_environment() == "direct"
