"""FastAPI application entry point for hakimi-proxy."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from hakimi_proxy.adapters.aistudio import AIStudioAdapter
from hakimi_proxy.adapters.antigravity import AntigravityAdapter
from hakimi_proxy.auth import BearerAuthMiddleware
from hakimi_proxy.config import get_config_path, load_config_from_env, save_config
from hakimi_proxy.metering.pricing import load_custom_pricing
from hakimi_proxy.metering.store import UsageStore
from hakimi_proxy.oauth import AntigravityOAuthManager
from hakimi_proxy.pool import CredentialPool
from hakimi_proxy.proxy import configure_proxy_environment
from hakimi_proxy.routes import chat, models, responses, usage
from hakimi_proxy.routes import admin
from hakimi_proxy.web import index_html

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

    app = FastAPI(title="hakimi-proxy", version="0.1.0", lifespan=_lifespan)

    # Auth middleware
    app.add_middleware(BearerAuthMiddleware, auth_token=config.auth_token)

    # Build credential pool
    pool = CredentialPool(cooldown_seconds=config.cooldown_seconds)
    for cred in config.aistudio_credentials:
        pool.add_aistudio(cred)
    for cred in config.antigravity_credentials:
        pool.add_antigravity(cred)

    logger.info(
        "Credential pool: %d AI Studio, %d Antigravity",
        len(config.aistudio_credentials),
        len(config.antigravity_credentials),
    )

    # Store app state
    app.state.pool = pool
    app.state.store = UsageStore(config.db_path)
    app.state.aistudio = AIStudioAdapter(proxy=config.proxy)
    app.state.antigravity = AntigravityAdapter(proxy=config.proxy)
    # Persist OAuth refresh-token rotation without exposing credentials to the UI.
    app.state.antigravity.on_credential_update = lambda: save_config(app.state.config, get_config_path())
    oauth_credential = next(iter(config.antigravity_credentials), None)
    app.state.antigravity_oauth = AntigravityOAuthManager(
        proxy=config.proxy,
        client_id=oauth_credential.client_id if oauth_credential else "",
        client_secret=oauth_credential.client_secret if oauth_credential else "",
    )
    app.state.max_retries = config.max_retries
    app.state.config = config
    app.state.proxy_source = proxy_source

    # Register routes
    app.include_router(chat.router)
    app.include_router(responses.router)
    app.include_router(models.router)
    app.include_router(usage.router)
    app.include_router(admin.router)

    @app.get("/", response_class=HTMLResponse)
    async def web_ui():
        return index_html

    @app.get("/ui", response_class=HTMLResponse)
    async def web_ui_alias():
        return index_html

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
        }

    return app


app = create_app()


def main():
    """Run the server with uvicorn."""
    import uvicorn

    config = load_config_from_env()
    uvicorn.run(
        "hakimi_proxy.main:app",
        host=config.host,
        port=config.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
