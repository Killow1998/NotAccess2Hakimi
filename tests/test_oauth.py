import time
from base64 import urlsafe_b64decode
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

from hakimi_proxy import oauth as oauth_module
from hakimi_proxy.oauth import AntigravityOAuthManager, ANTIGRAVITY_CALLBACK_URI, _OAuthSession


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
    manager = AntigravityOAuthManager(client_secret="")

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
