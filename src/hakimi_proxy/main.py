"""FastAPI application entry point for hakimi-proxy."""

from __future__ import annotations

import logging
import re
import uuid
import sys
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from hakimi_proxy import __version__
from hakimi_proxy.adapters.aistudio import AIStudioAdapter
from hakimi_proxy.adapters.antigravity import AntigravityAdapter
from hakimi_proxy.auth import BearerAuthMiddleware
from hakimi_proxy.access import AccessStore, router as access_router
from hakimi_proxy.config import get_config_path, load_config_from_env, save_config
from hakimi_proxy.diagnostics import DiagnosticJournal
from hakimi_proxy.metering.pricing import load_custom_pricing
from hakimi_proxy.metering.store import UsageStore
from hakimi_proxy.oauth import AntigravityOAuthManager, resolve_oauth_client
from hakimi_proxy.pool import CredentialPool
from hakimi_proxy.proxy import configure_proxy_environment
from hakimi_proxy.routes import chat, models, responses, usage
from hakimi_proxy.routes import admin
from hakimi_proxy.web import _index_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield
    app.state.antigravity_oauth.close()


def create_app() -> FastAPI:
    """Build the FastAPI app with all routes and middleware."""
    config = load_config_from_env()
    proxy_source = configure_proxy_environment(config.proxy)
    logger.info("Network proxy source: %s", proxy_source)

    # Load custom pricing overrides if present
    load_custom_pricing("pricing.yaml")

    app = FastAPI(title="hakimi-proxy", version=__version__, lifespan=_lifespan)

    # Auth middleware
    app.add_middleware(BearerAuthMiddleware, auth_token=config.auth_token)

    # Build credential pool
    pool = CredentialPool(cooldown_seconds=config.cooldown_seconds)
    pool.validate_reconfiguration(config.aistudio_credentials, config.antigravity_credentials, config.remote_credentials)
    for cred in config.aistudio_credentials:
        pool.add_aistudio(cred)
    for cred in config.antigravity_credentials:
        pool.add_antigravity(cred)
    for cred in config.remote_credentials:
        pool.add_remote(cred)

    logger.info(
        "Credential pool: %d AI Studio, %d Antigravity",
        len(config.aistudio_credentials),
        len(config.antigravity_credentials),
    )

    # Store app state
    app.state.pool = pool
    app.state.store = UsageStore(config.db_path)
    app.state.access = AccessStore(str(config.db_path) + '.access.sqlite3')
    app.state.aistudio = AIStudioAdapter(proxy=config.proxy)
    app.state.antigravity = AntigravityAdapter(proxy=config.proxy)
    app.state.upstream_client_factory = lambda proxy_url=None: (
        httpx.AsyncClient(proxy=proxy_url) if proxy_url else httpx.AsyncClient()
    )
    # Persist OAuth refresh-token rotation without exposing credentials to the UI.
    app.state.antigravity.on_credential_update = lambda: save_config(app.state.config, get_config_path())
    client_id, client_secret = resolve_oauth_client(config)
    app.state.antigravity_oauth = AntigravityOAuthManager(
        proxy=config.proxy,
        client_id=client_id,
        client_secret=client_secret,
    )
    app.state.max_retries = config.max_retries
    app.state.config = config
    app.state.proxy_source = proxy_source
    app.state.diagnostics = DiagnosticJournal()
    app.state.diagnostics.record(
        "application_configured",
        version=__version__,
        proxy_source=proxy_source,
        aistudio_credentials=len(config.aistudio_credentials),
        antigravity_credentials=len(config.antigravity_credentials),
        total_credentials=len(pool.all_credentials),
    )

    @app.middleware("http")
    async def record_request_diagnostic(request, call_next):
        supplied = request.headers.get("X-EMP-Request-ID", "")
        request_id = supplied if re.fullmatch(r"[0-9a-f]{16,32}", supplied) else uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            app.state.diagnostics.record(
                "http_request",
                level="error",
                request_id=request_id,
                method=request.method,
                route="<unmatched>",
                status=500,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            raise

        route = request.scope.get("route")
        route_path = getattr(route, "path", "<unmatched>")
        should_record = route_path.startswith("/v1/") or (
            request.method != "GET" and route_path.startswith("/api/")
        )
        if should_record:
            app.state.diagnostics.record(
                "http_request",
                level="warning" if response.status_code >= 400 else "info",
                request_id=request_id,
                method=request.method,
                route=route_path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
        response.headers["X-Request-ID"] = request_id
        return response

    # Register routes
    app.include_router(chat.router)
    app.include_router(responses.router)
    app.include_router(models.router)
    app.include_router(usage.router)
    app.include_router(admin.router)
    app.include_router(access_router)

    @app.get("/", response_class=HTMLResponse)
    async def web_ui():
        return _index_path.read_text(encoding="utf-8")

    @app.get("/ui", response_class=HTMLResponse)
    async def web_ui_alias():
        return _index_path.read_text(encoding="utf-8")

    @app.get("/healthz")
    async def healthz():
        pool = app.state.pool
        status = pool.get_status()
        return {
            "status": "ok",
            "active_credentials": pool.get_active_count(),
            "total_credentials": len(pool.all_credentials),
            "in_flight_requests": sum(item["in_flight"] for item in status),
            "proxy_source": app.state.proxy_source,
            "auth_enabled": bool(app.state.config.auth_token),
            "diagnostics": {
                "enabled": app.state.diagnostics.enabled,
                "path": app.state.diagnostics.display_path,
            },
        }

    @app.get("/readyz")
    async def readyz():
        pool = app.state.pool
        status = pool.get_status()
        active_credentials = pool.get_active_count()
        snapshot = {
            "status": "ready" if active_credentials else "not_ready",
            "active_credentials": active_credentials,
            "total_credentials": len(pool.all_credentials),
            "in_flight_requests": sum(item["in_flight"] for item in status),
        }
        if active_credentials:
            return snapshot
        snapshot["reason"] = "no_active_credentials"
        return JSONResponse(status_code=503, content=snapshot)

    return app


app = create_app()


def main():
    """Run the stable server; development reload is an explicit uvicorn command."""
    import uvicorn

    config = app.state.config
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
