import time

from hakimi_proxy.oauth import AntigravityOAuthManager, _OAuthSession


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
