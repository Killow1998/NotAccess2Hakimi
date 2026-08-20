"""Admin API routes for config management via Web UI."""

from __future__ import annotations

import logging
import re
import time

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from hakimi_proxy.config import (
    AIStudioCredential,
    AntigravityCredential,
    get_config_path,
    load_config,
    save_config,
)
from hakimi_proxy.pool import CredentialPool
from hakimi_proxy.errors import classify_exception, classify_response
from hakimi_proxy.proxy import configure_proxy_environment
from hakimi_proxy.oauth import AntigravityOAuthManager, exchange_oauth_code

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
TEST_MODELS = {
    "aistudio": "gemini-3.7-flash",
    "antigravity": "antigravity/gemini-3.7-flash-tiered",
}


class AIStudioCredIn(BaseModel):
    id: str
    api_key: str
    project: str = ""
    account: str = ""


class AIStudioCredUpdate(BaseModel):
    api_key: str | None = None
    project: str | None = None
    account: str | None = None


class AntigravityCredIn(BaseModel):
    id: str
    client_id: str
    client_secret: str
    refresh_token: str
    account: str = ""
    access_token: str = ""
    expires_at: float = 0.0
    project: str = ""
    auto_onboard: bool = False


class AntigravityCredUpdate(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    refresh_token: str | None = None
    account: str | None = None
    project: str | None = None
    auto_onboard: bool | None = None


class AntigravityOAuthCompleteIn(BaseModel):
    state: str
    callback_url: str = ""
    code: str = ""


class SettingsIn(BaseModel):
    host: str = "127.0.0.1"
    port: int = 12345
    auth_token: str = ""
    max_retries: int = 3
    cooldown_seconds: int = 60
    db_path: str = "hakimi.db"
    proxy: str = ""


def _safe_upstream_error(response: httpx.Response) -> dict[str, object]:
    """Expose the shared safe provider error shape."""
    return classify_response(response).public()


def _health(status: dict) -> str:
    state = status.get("state")
    if state == "cooldown":
        return "cooldown"
    if state == "disabled":
        return "reauth_required" if status.get("last_error_type") == "upstream_auth_error" else "disabled"
    success = status.get("last_success_at") or 0
    failure = status.get("last_failure_at") or 0
    if not success and not failure:
        return "unknown"
    return "healthy" if success >= failure else "degraded"


def _runtime_status(status: dict) -> dict[str, object]:
    return {
        "state": status.get("state", "unknown"),
        "health": _health(status),
        "cooldown_remaining": status.get("cooldown_remaining", 0),
        "failure_count": status.get("failure_count", 0),
        "in_flight": status.get("in_flight", 0),
        "last_success_at": status.get("last_success_at"),
        "last_failure_at": status.get("last_failure_at"),
        "last_error_type": status.get("last_error_type"),
        "last_error_message": status.get("last_error_message"),
        "last_latency_ms": status.get("last_latency_ms"),
        "last_model": status.get("last_model"),
        "last_tested_at": status.get("last_tested_at"),
        "last_test_ok": status.get("last_test_ok"),
    }


def _reload_pool(request: Request, config) -> None:
    """Rebuild the credential pool from config and update app state."""
    pool = CredentialPool(cooldown_seconds=config.cooldown_seconds)
    for cred in config.aistudio_credentials:
        pool.add_aistudio(cred)
    for cred in config.antigravity_credentials:
        pool.add_antigravity(cred)
    request.app.state.pool = pool
    request.app.state.max_retries = config.max_retries
    request.app.state.aistudio.proxy = config.proxy
    request.app.state.antigravity.proxy = config.proxy
    oauth_manager = getattr(request.app.state, "antigravity_oauth", None)
    if oauth_manager is not None:
        oauth_manager.proxy = config.proxy
        oauth_credential = next(iter(config.antigravity_credentials), None)
        if oauth_credential:
            oauth_manager.client_id = oauth_credential.client_id
            oauth_manager.client_secret = oauth_credential.client_secret
    request.app.state.config = config


def _load_and_save(request: Request, config) -> None:
    """Save config to disk and rebuild pool."""
    save_config(config, get_config_path())
    _reload_pool(request, config)


# --- Settings ---

@router.get("/config")
async def get_settings(request: Request):
    config = request.app.state.config
    return {
        "host": config.host,
        "port": config.port,
        "auth_token": config.auth_token,
        "max_retries": config.max_retries,
        "cooldown_seconds": config.cooldown_seconds,
        "db_path": config.db_path,
        "proxy": config.proxy,
        "proxy_source": getattr(request.app.state, "proxy_source", "unknown"),
        "config_file": get_config_path(),
    }


@router.put("/config")
async def update_settings(settings: SettingsIn, request: Request):
    config = request.app.state.config
    config.host = settings.host
    config.port = settings.port
    config.auth_token = settings.auth_token
    config.max_retries = settings.max_retries
    config.cooldown_seconds = settings.cooldown_seconds
    config.db_path = settings.db_path
    config.proxy = settings.proxy
    request.app.state.proxy_source = configure_proxy_environment(config.proxy)
    _load_and_save(request, config)
    logger.info("Settings updated via Web UI")
    return {
        "status": "ok",
        "proxy_source": request.app.state.proxy_source,
        "message": "Settings saved. Restart required for host/port/db_path changes.",
    }


# --- AI Studio credentials ---

@router.post("/credentials/aistudio")
async def add_aistudio(cred: AIStudioCredIn, request: Request):
    config = request.app.state.config
    if not cred.api_key.strip():
        return JSONResponse(status_code=422, content={"error": {"message": "api_key is required"}})
    # Check for duplicate ID
    if any(c.id == cred.id for c in config.aistudio_credentials):
        return JSONResponse(status_code=409, content={"error": {"message": f"Credential '{cred.id}' already exists"}})
    new_cred = AIStudioCredential(
        id=cred.id, api_key=cred.api_key, project=cred.project, account=cred.account,
    )
    config.aistudio_credentials.append(new_cred)
    _load_and_save(request, config)
    logger.info("AI Studio credential added: %s", cred.id)
    return {"status": "ok"}


@router.put("/credentials/aistudio/{cred_id}")
async def update_aistudio(cred_id: str, cred: AIStudioCredUpdate, request: Request):
    config = request.app.state.config
    for i, c in enumerate(config.aistudio_credentials):
        if c.id == cred_id:
            api_key = cred.api_key.strip() if cred.api_key and cred.api_key.strip() else c.api_key
            if not api_key:
                return JSONResponse(status_code=422, content={"error": {"message": "api_key is required"}})
            config.aistudio_credentials[i] = AIStudioCredential(
                id=c.id,
                api_key=api_key,
                project=c.project if cred.project is None else cred.project.strip(),
                account=c.account if cred.account is None else cred.account.strip(),
            )
            _load_and_save(request, config)
            return {"status": "ok"}
    return JSONResponse(status_code=404, content={"error": {"message": "Not found"}})


@router.delete("/credentials/aistudio/{cred_id}")
async def delete_aistudio(cred_id: str, request: Request):
    config = request.app.state.config
    before = len(config.aistudio_credentials)
    config.aistudio_credentials = [c for c in config.aistudio_credentials if c.id != cred_id]
    if len(config.aistudio_credentials) == before:
        return JSONResponse(status_code=404, content={"error": {"message": "Not found"}})
    _load_and_save(request, config)
    logger.info("AI Studio credential deleted: %s", cred_id)
    return {"status": "ok"}


# --- Antigravity credentials ---

def _oauth_manager(request: Request) -> AntigravityOAuthManager:
    manager = getattr(request.app.state, "antigravity_oauth", None)
    if manager is None:
        manager = AntigravityOAuthManager(proxy=request.app.state.config.proxy)
        request.app.state.antigravity_oauth = manager
    return manager


def _oauth_credential_id(config, account: str) -> str:
    base = re.sub(r"[^a-z0-9._-]+", "-", account.lower()).strip("-._") or "antigravity"
    candidate = f"antigravity-{base}"
    existing = {credential.id for credential in config.antigravity_credentials}
    if candidate not in existing:
        return candidate
    suffix = 2
    while f"{candidate}-{suffix}" in existing:
        suffix += 1
    return f"{candidate}-{suffix}"


@router.post("/credentials/antigravity/oauth/start")
async def start_antigravity_oauth(request: Request):
    try:
        return _oauth_manager(request).start()
    except (OSError, RuntimeError) as exc:
        logger.warning("Antigravity OAuth callback listener unavailable: %s", exc)
        return JSONResponse(
            status_code=409,
            content={"error": {"message": str(exc)}},
        )


async def _complete_antigravity_oauth(request: Request, state: str):
    manager = _oauth_manager(request)
    snapshot = manager.snapshot(state)
    if snapshot is None:
        return JSONResponse(status_code=404, content={"error": {"message": "OAuth 登录会话不存在或已过期"}})
    if snapshot.get("status") != "pending":
        return snapshot

    claimed = manager.claim_code(state)
    if claimed is None:
        return manager.snapshot(state) or snapshot

    code, redirect_uri = claimed
    try:
        bundle = await exchange_oauth_code(
            code,
            redirect_uri,
            manager.proxy,
            manager.client_id,
            manager.client_secret,
        )
        config = request.app.state.config
        credential_id = _oauth_credential_id(config, bundle.account)
        config.antigravity_credentials.append(AntigravityCredential(
            id=credential_id,
            client_id=bundle.client_id,
            client_secret=bundle.client_secret,
            refresh_token=bundle.refresh_token,
            account=bundle.account,
            access_token=bundle.access_token,
            expires_at=bundle.expires_at,
        ))
        try:
            _load_and_save(request, config)
        except Exception:
            config.antigravity_credentials.pop()
            raise
    except Exception as exc:
        message = str(exc).strip() or type(exc).__name__
        manager.fail(state, message)
        return {"status": "error", "message": message[:240]}

    manager.complete(state, credential_id, bundle.account)
    return {"status": "ok", "credential_id": credential_id, "account": bundle.account}


@router.get("/credentials/antigravity/oauth/status/{state}")
async def antigravity_oauth_status(state: str, request: Request):
    return await _complete_antigravity_oauth(request, state)


@router.post("/credentials/antigravity/oauth/complete")
async def complete_antigravity_oauth(payload: AntigravityOAuthCompleteIn, request: Request):
    manager = _oauth_manager(request)
    accepted = manager.record_manual_callback(
        payload.state,
        callback_url=payload.callback_url,
        code=payload.code,
    )
    if not accepted:
        snapshot = manager.snapshot(payload.state)
        if snapshot and snapshot.get("status") in {"processing", "ok", "error"}:
            return snapshot
        return JSONResponse(status_code=400, content={"error": {"message": "OAuth 回调无效、重复或已过期"}})
    return await _complete_antigravity_oauth(request, payload.state)

@router.post("/credentials/antigravity")
async def add_antigravity(cred: AntigravityCredIn, request: Request):
    config = request.app.state.config
    if not all(value.strip() for value in (cred.client_id, cred.client_secret, cred.refresh_token)):
        return JSONResponse(status_code=422, content={"error": {"message": "OAuth credentials are required"}})
    if any(c.id == cred.id for c in config.antigravity_credentials):
        return JSONResponse(status_code=409, content={"error": {"message": f"Credential '{cred.id}' already exists"}})
    new_cred = AntigravityCredential(
        id=cred.id,
        client_id=cred.client_id,
        client_secret=cred.client_secret,
        refresh_token=cred.refresh_token,
        account=cred.account,
        access_token=cred.access_token,
        expires_at=cred.expires_at,
        project=cred.project,
        auto_onboard=cred.auto_onboard,
    )
    config.antigravity_credentials.append(new_cred)
    _load_and_save(request, config)
    logger.info("Antigravity credential added: %s", cred.id)
    return {"status": "ok"}


@router.put("/credentials/antigravity/{cred_id}")
async def update_antigravity(cred_id: str, cred: AntigravityCredUpdate, request: Request):
    config = request.app.state.config
    for i, c in enumerate(config.antigravity_credentials):
        if c.id == cred_id:
            client_id = cred.client_id.strip() if cred.client_id and cred.client_id.strip() else c.client_id
            client_secret = cred.client_secret.strip() if cred.client_secret and cred.client_secret.strip() else c.client_secret
            refresh_token = cred.refresh_token.strip() if cred.refresh_token and cred.refresh_token.strip() else c.refresh_token
            account = c.account if cred.account is None else cred.account.strip()
            if not client_id or not client_secret or not refresh_token:
                return JSONResponse(status_code=422, content={"error": {"message": "OAuth credentials are required"}})
            oauth_changed = (client_id, client_secret, refresh_token) != (
                c.client_id, c.client_secret, c.refresh_token,
            )
            if oauth_changed:
                project = (
                    cred.project.strip()
                    if cred.project is not None and cred.project.strip() != c.project
                    else ""
                )
                access_token, expires_at = "", 0.0
            else:
                project = c.project if cred.project is None else cred.project.strip()
                access_token, expires_at = c.access_token, c.expires_at
            config.antigravity_credentials[i] = AntigravityCredential(
                id=c.id,
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                account=account,
                access_token=access_token,
                expires_at=expires_at,
                project=project,
                auto_onboard=c.auto_onboard if cred.auto_onboard is None else cred.auto_onboard,
            )
            _load_and_save(request, config)
            return {"status": "ok"}
    return JSONResponse(status_code=404, content={"error": {"message": "Not found"}})


@router.delete("/credentials/antigravity/{cred_id}")
async def delete_antigravity(cred_id: str, request: Request):
    config = request.app.state.config
    before = len(config.antigravity_credentials)
    config.antigravity_credentials = [c for c in config.antigravity_credentials if c.id != cred_id]
    if len(config.antigravity_credentials) == before:
        return JSONResponse(status_code=404, content={"error": {"message": "Not found"}})
    _load_and_save(request, config)
    logger.info("Antigravity credential deleted: %s", cred_id)
    return {"status": "ok"}


# --- Credentials list with pool status ---

@router.get("/credentials")
async def list_credentials(request: Request):
    config = request.app.state.config
    pool = request.app.state.pool
    status_map = {s["id"]: s for s in pool.get_status()}

    aistudio = []
    for c in config.aistudio_credentials:
        s = status_map.get(c.id, {})
        aistudio.append({
            "id": c.id,
            "api_key_set": bool(c.api_key),
            "project": c.project,
            "account": c.account,
            "kind": "aistudio",
            **_runtime_status(s),
        })

    antigravity = []
    for c in config.antigravity_credentials:
        s = status_map.get(c.id, {})
        antigravity.append({
            "id": c.id,
            "account": c.account,
            "client_id": c.client_id,
            "client_secret_set": bool(c.client_secret),
            "refresh_token_set": bool(c.refresh_token),
            "access_token_expires_at": c.expires_at or None,
            "project": c.project,
            "auto_onboard": c.auto_onboard,
            "kind": "antigravity",
            **_runtime_status(s),
        })

    return {"aistudio": aistudio, "antigravity": antigravity}


@router.post("/credentials/{kind}/{cred_id}/test")
async def test_credential(kind: str, cred_id: str, request: Request):
    model = TEST_MODELS.get(kind)
    if model is None:
        return JSONResponse(status_code=400, content={"error": {"message": "Unknown credential provider"}})

    credential = next(
        (c for c in request.app.state.pool.all_credentials if c.kind == kind and c.id == cred_id),
        None,
    )
    if credential is None:
        return JSONResponse(status_code=404, content={"error": {"message": "Credential not found"}})

    pool = request.app.state.pool
    try:
        credential = await pool.acquire(kind=kind, credential_id=cred_id, timeout_seconds=30)
    except Exception as exc:
        if getattr(exc, "reason", "") == "busy_timeout":
            return JSONResponse(status_code=503, content={"error": {"type": "capacity_exhausted", "message": "Credential is busy"}})
        return JSONResponse(status_code=404, content={"error": {"message": "Credential not available"}})

    adapter = request.app.state.aistudio if kind == "aistudio" else request.app.state.antigravity
    proxy_url = request.app.state.config.proxy or None
    client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else httpx.AsyncClient()
    response = None
    started = time.perf_counter()
    try:
        response = await adapter.forward(
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply exactly: OK"}],
                "max_tokens": 8,
            },
            credential,
            False,
            client,
        )
        if response.status_code != 200:
            failure = classify_response(response)
            credential.last_tested_at = time.time()
            credential.last_test_ok = False
            pool.mark_failure(credential, failure.type, failure.message, latency_ms=round((time.perf_counter() - started) * 1000), model=model)
            if failure.credential_action == "cooldown":
                pool.mark_cooldown(credential, failure.retry_after)
            elif failure.credential_action == "disable":
                pool.mark_disabled(credential)
            return JSONResponse(
                status_code=502,
                content={
                    "error": failure.public(),
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                },
            )
        credential.last_tested_at = time.time()
        credential.last_test_ok = True
        pool.mark_success(credential, latency_ms=round((time.perf_counter() - started) * 1000), model=model)
        return {
            "status": "ok",
            "credential_id": cred_id,
            "provider": kind,
            "model": model,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        failure = classify_exception(exc)
        logger.warning("Credential test failed for %s: %s", cred_id, failure.message)
        credential.last_tested_at = time.time()
        credential.last_test_ok = False
        pool.mark_failure(credential, failure.type, failure.message, latency_ms=round((time.perf_counter() - started) * 1000), model=model)
        if failure.credential_action == "cooldown":
            pool.mark_cooldown(credential, failure.retry_after)
        elif failure.credential_action == "disable":
            pool.mark_disabled(credential)
        return JSONResponse(
            status_code=502,
            content={
                "error": failure.public(),
                "latency_ms": round((time.perf_counter() - started) * 1000),
            },
        )
    finally:
        if response is not None:
            await response.aclose()
        await client.aclose()
        await pool.release(credential)


# --- Usage summary for dashboard ---

@router.get("/usage/summary")
async def usage_summary(request: Request):
    store = request.app.state.store
    rows = store.get_usage()
    total_cost = sum(r.get("cost_usd", 0) for r in rows)
    total_requests = sum(r.get("request_count", 0) for r in rows)
    total_input = sum(r.get("input_tokens", 0) for r in rows)
    total_output = sum(r.get("output_tokens", 0) for r in rows)

    # Per-credential breakdown
    by_cred: dict[str, dict] = {}
    for r in rows:
        cid = r["credential_id"]
        if cid not in by_cred:
            by_cred[cid] = {"cost_usd": 0, "requests": 0, "input_tokens": 0, "output_tokens": 0}
        by_cred[cid]["cost_usd"] += r.get("cost_usd", 0)
        by_cred[cid]["requests"] += r.get("request_count", 0)
        by_cred[cid]["input_tokens"] += r.get("input_tokens", 0)
        by_cred[cid]["output_tokens"] += r.get("output_tokens", 0)

    # Per-model breakdown
    by_model: dict[str, dict] = {}
    for r in rows:
        m = r["model"]
        if m not in by_model:
            by_model[m] = {"cost_usd": 0, "requests": 0, "input_tokens": 0, "output_tokens": 0}
        by_model[m]["cost_usd"] += r.get("cost_usd", 0)
        by_model[m]["requests"] += r.get("request_count", 0)
        by_model[m]["input_tokens"] += r.get("input_tokens", 0)
        by_model[m]["output_tokens"] += r.get("output_tokens", 0)

    return {
        "total_cost_usd": round(total_cost, 6),
        "total_requests": total_requests,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "by_credential": [
            {"credential_id": k, **v} for k, v in sorted(by_cred.items(), key=lambda x: -x[1]["cost_usd"])
        ],
        "by_model": [
            {"model": k, **v} for k, v in sorted(by_model.items(), key=lambda x: -x[1]["cost_usd"])
        ],
    }
