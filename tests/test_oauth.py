import time
from base64 import urlsafe_b64decode
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

from hakimi_proxy import oauth as oauth_module
from hakimi_proxy.oauth import AntigravityOAuthManager, ANTIGRAVITY_CALLBACK_URI, _OAuthSession


def test_clean_install_has_complete_client_without_agy(monkeypatch):
    from hakimi_proxy.config import ProxyConfig
    import subprocess

    def unexpected_process(*args, **kwargs):
        raise AssertionError("OAuth must not invoke an installed application")

    monkeypatch.setattr(subprocess, "Popen", unexpected_process)
    monkeypatch.setattr(oauth_module, "OAUTH_CLIENT_ID", oauth_module.DEFAULT_CLIENT_ID)
    monkeypatch.setattr(oauth_module, "OAUTH_CLIENT_SECRET", oauth_module.DEFAULT_CLIENT_SECRET)
    client_id, client_secret = oauth_module.resolve_oauth_client(ProxyConfig())
    assert client_secret
    manager = AntigravityOAuthManager(client_id=client_id, client_secret=client_secret)
    session = manager.start("remote")
    assert client_secret not in str(session)
    assert manager.record_callback(session["state"], "test-code", "")
    assert manager.claim_code(session["state"])[3:] == (client_id, client_secret)


def test_manual_callback_accepts_full_url_and_claims_code_once():
    manager = AntigravityOAuthManager(callback_port=0, client_secret="client-secret")
    manager._session = _OAuthSession(
        state="state-1",
        redirect_uri="http://localhost:51121/oauth-callback",
        authorization_url="",
        created_at=time.time(),
        expires_at=time.time() + 300,
    )
    callback = "http://localhost:51121/oauth-callback?code=one-time&state=state-1"

    assert manager.record_manual_callback("state-1", callback_url=callback)
    assert manager.claim_code("state-1")[0] == "one-time"
    assert not manager.record_manual_callback("state-1", callback_url=callback)


def test_manual_callback_rejects_wrong_path_or_state():
    manager = AntigravityOAuthManager(callback_port=0, client_secret="client-secret")
    manager._session = _OAuthSession(
        state="state-1",
        redirect_uri="http://localhost:51121/oauth-callback",
        authorization_url="",
        created_at=time.time(),
        expires_at=time.time() + 300,
    )
    assert not manager.record_manual_callback(
        "state-1",
        callback_url="http://localhost:51121/not-callback?code=one-time&state=state-1",
    )
    assert not manager.record_manual_callback(
        "wrong-state",
        callback_url="http://localhost:51121/oauth-callback?code=one-time&state=wrong-state",
    )


def test_remote_start_does_not_bind_callback_listener(monkeypatch):
    def unexpected_listener(*args, **kwargs):
        raise AssertionError("remote OAuth must not bind a callback socket")

    monkeypatch.setattr(oauth_module, "_CallbackServer", unexpected_listener)
    manager = AntigravityOAuthManager(client_id="public-client", client_secret="")

    session = manager.start(mode="remote")

    assert session["mode"] == "remote"
    assert session["redirect_uri"] == ANTIGRAVITY_CALLBACK_URI
    assert manager._server is None

    params = parse_qs(urlsplit(session["authorization_url"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["redirect_uri"] == [ANTIGRAVITY_CALLBACK_URI]
    assert "openid" in params["scope"][0].split()
    verifier = manager._session.code_verifier
    challenge = urlsafe_b64decode(params["code_challenge"][0] + "==")
    assert challenge == sha256(verifier.encode("ascii")).digest()


def test_oauth_start_rejects_unknown_mode():
    manager = AntigravityOAuthManager(client_secret="client-secret")

    try:
        manager.start(mode="automatic")
    except ValueError as exc:
        assert str(exc) == "OAuth mode must be 'local' or 'remote'"
    else:
        raise AssertionError("unknown OAuth mode was accepted")


def test_oauth_claim_keeps_client_identity_from_authorization():
    manager = AntigravityOAuthManager(client_id="client-A", client_secret="secret-A")
    session = manager.start()
    manager.client_id, manager.client_secret = "client-B", ""
    assert manager.record_callback(session["state"], "code-A", "")
    claimed = manager.claim_code(session["state"])
    assert claimed[3:] == ("client-A", "secret-A")


def test_explicit_public_client_does_not_inherit_environment_secret(monkeypatch):
    monkeypatch.setattr(oauth_module, "OAUTH_CLIENT_SECRET", "environment-secret")
    manager = AntigravityOAuthManager(client_id="public-client", client_secret="")
    assert manager.client_secret == ""


def test_client_pair_precedence_never_fills_public_secret(monkeypatch):
    from hakimi_proxy.config import ProxyConfig, AntigravityCredential
    monkeypatch.setattr(oauth_module, "OAUTH_CLIENT_ID", "env-id")
    monkeypatch.setattr(oauth_module, "OAUTH_CLIENT_SECRET", "env-secret")
    config = ProxyConfig()
    assert oauth_module.resolve_oauth_client(config) == ("env-id", "env-secret")
    config.antigravity_client_id = "app-id"
    assert oauth_module.resolve_oauth_client(config) == ("app-id", "")
    config.antigravity_client_secret = "app-secret"
    config.antigravity_credentials = [AntigravityCredential("public", "account-id", "", "refresh")]
    assert oauth_module.resolve_oauth_client(config) == ('app-id', 'app-secret')
    config.antigravity_client_id = ''
    assert oauth_module.resolve_oauth_client(config) == ("account-id", "")


def test_default_client_missing_secret_fails_before_authorization():
    import pytest
    manager = AntigravityOAuthManager(client_id=oauth_module.DEFAULT_CLIENT_ID, client_secret='')
    with pytest.raises(oauth_module.OAuthConfigurationError):
        manager.start('remote')
    assert manager._session is None
    manager.configure_client(oauth_module.DEFAULT_CLIENT_ID, 'configured-secret')
    session = manager.start('remote')
    assert 'configured-secret' not in str(session)
    manager.record_callback(session['state'], 'code', '')
    assert manager.claim_code(session['state'])[4] == 'configured-secret'


def test_default_client_legacy_config_can_sign_in_without_manual_secret():
    from hakimi_proxy.config import ProxyConfig, AntigravityCredential
    config = ProxyConfig()
    for source in ("application", "credential"):
        config.antigravity_client_id = oauth_module.DEFAULT_CLIENT_ID if source == "application" else ""
        config.antigravity_credentials = [AntigravityCredential(
            "legacy", oauth_module.DEFAULT_CLIENT_ID, "", "fixture-refresh"
        )]
        client_id, secret = oauth_module.resolve_oauth_client(config)
        assert secret == oauth_module.DEFAULT_CLIENT_SECRET
        manager = AntigravityOAuthManager(client_id=client_id, client_secret=secret)
        session = manager.start("remote")
        assert session["authorization_url"]
        assert secret not in str(session)
        assert config.antigravity_client_secret == ""
        assert config.antigravity_credentials[0].client_secret == ""
