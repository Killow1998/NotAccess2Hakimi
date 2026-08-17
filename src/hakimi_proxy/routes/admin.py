"""Admin API routes for config management via Web UI."""

from __future__ import annotations

import logging

import json

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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class AIStudioCredIn(BaseModel):
    id: str
    api_key: str
    project: str = ""
    account: str = ""


class AntigravityCredIn(BaseModel):
    id: str
    client_id: str
    client_secret: str
    refresh_token: str
    access_token: str = ""
    expires_at: float = 0.0


class SettingsIn(BaseModel):
    host: str = "127.0.0.1"
    port: int = 12345
    auth_token: str = ""
    max_retries: int = 3
    cooldown_seconds: int = 60
    db_path: str = "hakimi.db"
    proxy: str = ""


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
    _load_and_save(request, config)
    logger.info("Settings updated via Web UI")
    return {"status": "ok", "message": "Settings saved. Restart required for host/port/db_path changes."}


# --- AI Studio credentials ---

@router.post("/credentials/aistudio")
async def add_aistudio(cred: AIStudioCredIn, request: Request):
    config = request.app.state.config
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
async def update_aistudio(cred_id: str, cred: AIStudioCredIn, request: Request):
    config = request.app.state.config
    for i, c in enumerate(config.aistudio_credentials):
        if c.id == cred_id:
            config.aistudio_credentials[i] = AIStudioCredential(
                id=cred.id, api_key=cred.api_key, project=cred.project, account=cred.account,
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

@router.post("/credentials/antigravity")
async def add_antigravity(cred: AntigravityCredIn, request: Request):
    config = request.app.state.config
    if any(c.id == cred.id for c in config.antigravity_credentials):
        return JSONResponse(status_code=409, content={"error": {"message": f"Credential '{cred.id}' already exists"}})
    new_cred = AntigravityCredential(
        id=cred.id,
        client_id=cred.client_id,
        client_secret=cred.client_secret,
        refresh_token=cred.refresh_token,
        access_token=cred.access_token,
        expires_at=cred.expires_at,
    )
    config.antigravity_credentials.append(new_cred)
    _load_and_save(request, config)
    logger.info("Antigravity credential added: %s", cred.id)
    return {"status": "ok"}


@router.put("/credentials/antigravity/{cred_id}")
async def update_antigravity(cred_id: str, cred: AntigravityCredIn, request: Request):
    config = request.app.state.config
    for i, c in enumerate(config.antigravity_credentials):
        if c.id == cred_id:
            config.antigravity_credentials[i] = AntigravityCredential(
                id=cred.id,
                client_id=cred.client_id,
                client_secret=cred.client_secret,
                refresh_token=cred.refresh_token,
                access_token=cred.access_token,
                expires_at=cred.expires_at,
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
            "api_key": c.api_key[:10] + "..." if len(c.api_key) > 10 else c.api_key,
            "project": c.project,
            "account": c.account,
            "kind": "aistudio",
            "state": s.get("state", "unknown"),
            "cooldown_remaining": s.get("cooldown_remaining", 0),
            "failure_count": s.get("failure_count", 0),
        })

    antigravity = []
    for c in config.antigravity_credentials:
        s = status_map.get(c.id, {})
        antigravity.append({
            "id": c.id,
            "client_id": c.client_id[:15] + "..." if len(c.client_id) > 15 else c.client_id,
            "refresh_token": c.refresh_token[:10] + "..." if len(c.refresh_token) > 10 else c.refresh_token,
            "kind": "antigravity",
            "state": s.get("state", "unknown"),
            "cooldown_remaining": s.get("cooldown_remaining", 0),
            "failure_count": s.get("failure_count", 0),
        })

    return {"aistudio": aistudio, "antigravity": antigravity}


# --- Credential test ---

@router.post("/credentials/{kind}/{cred_id}/test")
async def test_credential(kind: str, cred_id: str, request: Request):
    """Test a specific credential with a simple chat request (bypasses pool)."""
    pool = request.app.state.pool
    config = request.app.state.config

    cred = None
    for c in pool.all_credentials:
        if c.id == cred_id:
            cred = c
            break
    if cred is None:
        return JSONResponse(status_code=404, content={"error": {"message": "Credential not found"}})

    if kind == "aistudio":
        adapter = request.app.state.aistudio
    elif kind == "antigravity":
        adapter = request.app.state.antigravity
    else:
        return JSONResponse(status_code=400, content={"error": {"message": "Invalid kind"}})

    body = {
        "model": "gemini-3.7-flash",
        "messages": [{"role": "user", "content": "Say hello in one sentence."}],
        "max_tokens": 100,
    }

    proxy_url = config.proxy or None
    client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else httpx.AsyncClient()
    try:
        resp = await adapter.forward(body, cred, False, client)
        if resp.status_code == 200:
            raw = resp.json()
            if adapter.kind == "antigravity":
                inner = raw.get("response", raw)
                candidates = inner.get("candidates", [])
                content = ""
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    content = "".join(p.get("text", "") for p in parts if "text" in p)
            else:
                content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = adapter.extract_usage(raw)
            return {"status": "ok", "content": content, "usage": usage}
        else:
            err_msg = f"HTTP {resp.status_code}"
            try:
                err_body = resp.json()
                err_msg += f": {json.dumps(err_body)[:300]}"
            except Exception:
                err_msg += f": {resp.text[:300]}"
            return {"status": "error", "message": err_msg}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        await client.aclose()


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
