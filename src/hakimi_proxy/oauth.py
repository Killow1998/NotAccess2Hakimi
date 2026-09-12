"""Browser OAuth flow for Antigravity credentials.

The flow uses Google's installed-app OAuth client with PKCE. The server
creates a listener-free Antigravity callback URL, so the authorization link can
be opened on any Google-accessible device; only the short-lived callback code
is returned to NA2H for exchange and storage.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

DEFAULT_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
# Shared installed-app client metadata, not an account credential.
# Source: router-for-me/CLIProxyAPI, internal/auth/antigravity/constants.go.
DEFAULT_CLIENT_SECRET = "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"
OAUTH_CLIENT_ID = os.environ.get("HAKIMI_ANTIGRAVITY_CLIENT_ID", DEFAULT_CLIENT_ID)
OAUTH_CLIENT_SECRET = os.environ.get(
    "HAKIMI_ANTIGRAVITY_CLIENT_SECRET",
    DEFAULT_CLIENT_SECRET if OAUTH_CLIENT_ID == DEFAULT_CLIENT_ID else "",
)
OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo?alt=json"
ANTIGRAVITY_CALLBACK_URI = "https://antigravity.google/oauth-callback"
OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
    "openid",
)
DEFAULT_CALLBACK_PORT = 51121
SESSION_TTL_SECONDS = 300


class OAuthConfigurationError(RuntimeError):
    pass


def validate_oauth_client(client_id: str, client_secret: str) -> None:
    if not client_id.strip() or (client_id == DEFAULT_CLIENT_ID and not client_secret.strip()):
        raise OAuthConfigurationError('Antigravity OAuth client configuration is incomplete. Configure the matching client secret before signing in.')


def resolve_client_secret(client_id: str, client_secret: str) -> str:
    """Complete the known shared client without changing a custom client pair."""
    if client_id == DEFAULT_CLIENT_ID and not client_secret:
        return DEFAULT_CLIENT_SECRET
    return client_secret


def resolve_oauth_client(config) -> tuple[str, str]:
    """Resolve a configured pair, completing only the known default application."""
    client_id, client_secret = OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET
    if config.antigravity_client_id.strip():
        client_id = config.antigravity_client_id.strip()
        client_secret = config.antigravity_client_secret.strip()
    else:
        credential = next(iter(config.antigravity_credentials), None)
        if credential and credential.client_id.strip():
            client_id = credential.client_id.strip()
            client_secret = credential.client_secret.strip()
    return client_id, resolve_client_secret(client_id, client_secret)


@dataclass(frozen=True)
class AntigravityOAuthBundle:
    client_id: str
    client_secret: str
    refresh_token: str
    access_token: str
    expires_at: float
    account: str


@dataclass
class _OAuthSession:
    state: str
    redirect_uri: str
    authorization_url: str
    created_at: float
    expires_at: float
    code: str = ""
    error: str = ""
    status: str = "pending"
    processing: bool = False
    credential_id: str = ""
    account: str = ""
    mode: str = "local"
    code_verifier: str = ""
    client_id: str = ""
    client_secret: str = ""


class _CallbackServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class _CallbackHandler(BaseHTTPRequestHandler):
    def __init__(self, manager: "AntigravityOAuthManager", *args: Any, **kwargs: Any) -> None:
        self.manager = manager
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlsplit(self.path)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
        accepted = parsed.path == "/oauth-callback" and self.manager.record_callback(
            params.get("state", ""), params.get("code", ""), params.get("error", "")
        )
        body = (
            "<h1>Antigravity 登录成功</h1><p>可以关闭此窗口，返回 Hakimi 控制台。</p>"
            if accepted
            else "<h1>Antigravity 登录失败</h1><p>请返回 Hakimi 控制台查看错误。</p>"
        )
        encoded = body.encode("utf-8")
        self.send_response(200 if accepted else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        return


class AntigravityOAuthManager:
    """Own one short-lived local OAuth session at a time."""

    def __init__(
        self,
        proxy: str = "",
        callback_port: int = DEFAULT_CALLBACK_PORT,
        client_id: str = OAUTH_CLIENT_ID,
        client_secret: str = OAUTH_CLIENT_SECRET,
    ) -> None:
        self.proxy = proxy
        self.callback_port = callback_port
        self.client_id = client_id.strip() or OAUTH_CLIENT_ID
        self.client_secret = client_secret.strip()
        self._lock = threading.Lock()
        self._session: _OAuthSession | None = None
        self._server: _CallbackServer | None = None

    def configure_client(self, client_id: str, client_secret: str) -> None:
        with self._lock:
            self.client_id, self.client_secret = client_id, client_secret

    def start(self, mode: str = "remote") -> dict[str, object]:
        if mode not in {"local", "remote"}:
            raise ValueError("OAuth mode must be 'local' or 'remote'")
        now = time.time()
        with self._lock:
            validate_oauth_client(self.client_id, self.client_secret)
            if (
                self._session
                and self._session.mode == mode
                and self._session.expires_at > now
                and self._session.status in {"pending", "processing"}
            ):
                return self._public_session(self._session)
            self._stop_server_locked()
            state = secrets.token_urlsafe(32)
            server: _CallbackServer | None = None
            port = self.callback_port
            if mode == "local":
                server = _CallbackServer(("127.0.0.1", self.callback_port), self._handler_type())
                port = int(server.server_address[1])
            redirect_uri = (
                f"http://localhost:{port}/oauth-callback"
                if mode == "local"
                else ANTIGRAVITY_CALLBACK_URI
            )
            code_verifier = _generate_code_verifier()
            authorization_url = _authorization_url(
                state,
                redirect_uri,
                self.client_id,
                code_challenge=_code_challenge(code_verifier),
            )
            session = _OAuthSession(
                state=state,
                redirect_uri=redirect_uri,
                authorization_url=authorization_url,
                created_at=now,
                expires_at=now + SESSION_TTL_SECONDS,
                mode=mode,
                code_verifier=code_verifier,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
            self._session = session
            self._server = server
            if server is not None:
                thread = threading.Thread(target=server.serve_forever, name="antigravity-oauth", daemon=True)
                thread.start()
            return self._public_session(session)

    def _handler_type(self):
        manager = self

        class Handler(_CallbackHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(manager, *args, **kwargs)

        return Handler

    def record_callback(self, state: str, code: str, error: str) -> bool:
        with self._lock:
            session = self._session
            if (
                not session
                or session.state != state
                or session.expires_at <= time.time()
                or session.status != "pending"
                or session.code
            ):
                return False
            if error:
                session.error = error[:160]
                session.status = "error"
                session.code_verifier = session.client_secret = ""
            elif code:
                session.code = code
            else:
                return False
            return True

    def record_manual_callback(self, state: str, callback_url: str = "", code: str = "", error: str = "") -> bool:
        """Accept a copied localhost callback URL or a one-time OAuth code."""
        if callback_url:
            parsed = urlsplit(callback_url.strip())
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.path.rstrip("/") != "/oauth-callback"
            ):
                return False
            params = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
            callback_state = params.get("state", "")
            if not callback_state:
                return False
            return self.record_callback(
                callback_state,
                params.get("code", ""),
                params.get("error", ""),
            )
        return self.record_callback(state, code, error)

    def snapshot(self, state: str) -> dict[str, object] | None:
        with self._lock:
            session = self._session
            if not session or session.state != state:
                return None
            if session.expires_at <= time.time() and session.status in {"pending", "processing"}:
                session.status = "error"
                session.error = "OAuth login timed out"
                session.code = session.code_verifier = session.client_secret = ""
            return {
                "status": "processing" if session.processing else session.status,
                "credential_id": session.credential_id,
                "account": session.account,
                "message": session.error,
            }

    def claim_code(self, state: str) -> tuple[str, str, str, str, str] | None:
        with self._lock:
            session = self._session
            if (not session or session.state != state or session.status != "pending"
                    or session.expires_at <= time.time() or not session.code):
                return None
            if session.processing:
                return None
            session.processing = True
            return (session.code, session.redirect_uri, session.code_verifier,
                    session.client_id, session.client_secret)

    def complete(self, state: str, credential_id: str, account: str) -> None:
        with self._lock:
            session = self._session
            if not session or session.state != state:
                return
            session.status = "ok"
            session.processing = False
            session.credential_id = credential_id
            session.account = account
            session.code = ""
            session.code_verifier = session.client_secret = ""
            self._stop_server_locked()

    def fail(self, state: str, message: str) -> None:
        with self._lock:
            session = self._session
            if not session or session.state != state:
                return
            session.status = "error"
            session.processing = False
            session.error = message[:240]
            session.code = ""
            session.code_verifier = session.client_secret = ""
            self._stop_server_locked()

    def close(self) -> None:
        with self._lock:
            self._session = None
            self._stop_server_locked()

    def _stop_server_locked(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.shutdown()
            server.server_close()

    @staticmethod
    def _public_session(session: _OAuthSession) -> dict[str, object]:
        return {
            "status": "pending",
            "state": session.state,
            "authorization_url": session.authorization_url,
            "redirect_uri": session.redirect_uri,
            "mode": session.mode,
            "expires_in": max(0, int(session.expires_at - time.time())),
        }


def _generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _authorization_url(
    state: str,
    redirect_uri: str,
    client_id: str = OAUTH_CLIENT_ID,
    *,
    code_challenge: str = "",
) -> str:
    params = {
        "access_type": "offline",
        "client_id": client_id,
        "prompt": "consent",
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(OAUTH_SCOPES),
        "state": state,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return OAUTH_AUTH_URL + "?" + urlencode(params)


async def exchange_oauth_code(
    code: str,
    redirect_uri: str,
    proxy: str = "",
    client_id: str = OAUTH_CLIENT_ID,
    client_secret: str = OAUTH_CLIENT_SECRET,
    code_verifier: str = "",
) -> AntigravityOAuthBundle:
    """Exchange a one-time authorization code and fetch the account email."""
    if not code or not redirect_uri:
        raise RuntimeError("OAuth callback is incomplete")
    validate_oauth_client(client_id, client_secret)
    async with httpx.AsyncClient(proxy=proxy or None) as client:
        token_data = {
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        # PKCE and client authentication are independent requirements.
        if client_secret:
            token_data["client_secret"] = client_secret
        if code_verifier:
            token_data["code_verifier"] = code_verifier
        response = await client.post(
            OAUTH_TOKEN_URL,
            data=token_data,
            timeout=30.0,
        )
        if response.status_code != 200:
            detail = ""
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = {}
            if isinstance(error_payload, dict):
                error_code = str(error_payload.get("error") or "").strip()
                error_description = str(error_payload.get("error_description") or "").strip()
                detail = ": ".join(part for part in (error_code, error_description) if part)
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(
                f"OAuth token exchange failed: HTTP {response.status_code}{suffix}"
            )
        payload = response.json()
        access_token = str(payload.get("access_token") or "").strip()
        refresh_token = str(payload.get("refresh_token") or "").strip()
        if not access_token or not refresh_token:
            raise RuntimeError("OAuth token exchange did not return both tokens")

        info = await client.get(
            OAUTH_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
        if info.status_code != 200:
            raise RuntimeError(f"OAuth account lookup failed: HTTP {info.status_code}")
        account = str(info.json().get("email") or "").strip()
        if not account:
            raise RuntimeError("OAuth account lookup returned no email")

    return AntigravityOAuthBundle(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        access_token=access_token,
        expires_at=time.time() + float(payload.get("expires_in", 3600)),
        account=account,
    )
