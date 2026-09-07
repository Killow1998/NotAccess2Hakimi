"""GET /v1/models route."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from hakimi_proxy.model_catalog import (
    list_model_discovery_entries,
    model_ids_for_providers,
    model_discovery_entry,
)

router = APIRouter()


def _configured_provider_flags(request: Request) -> tuple[bool, bool]:
    """Return whether each provider currently has configured credentials."""
    pool = getattr(request.app.state, "pool", None)
    credentials = pool.all_credentials if pool is not None else []
    return (
        any(credential.kind == "aistudio" for credential in credentials),
        any(credential.kind == "antigravity" for credential in credentials),
    )


def _configured_model_ids(request: Request) -> frozenset[str]:
    """Return models for providers that currently have configured credentials."""
    aistudio, antigravity = _configured_provider_flags(request)
    return model_ids_for_providers(aistudio=aistudio, antigravity=antigravity)


@router.get("/v1/models")
async def list_models(request: Request):
    aistudio, antigravity = _configured_provider_flags(request)
    return JSONResponse(content={
        "object": "list",
        "data": list_model_discovery_entries(
            aistudio=aistudio,
            antigravity=antigravity,
        ),
    })


@router.get("/v1/models/{model_id}")
async def get_model(model_id: str, request: Request):
    if model_id not in _configured_model_ids(request):
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Model not found: {model_id}", "type": "not_found_error"}},
        )
    return JSONResponse(content=model_discovery_entry(model_id))
