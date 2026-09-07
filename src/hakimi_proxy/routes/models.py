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
    return model_ids_for_providers(aistudio=aistudio, antigravity=antigravity) | frozenset(_remote_models(request))


def _remote_models(request):
    return sorted({'remote/' + c.group + '/' + m for c in request.app.state.config.remote_credentials for m in c.models})


@router.get("/v1/models")
async def list_models(request: Request):
    aistudio, antigravity = _configured_provider_flags(request)
    entries = list_model_discovery_entries(aistudio=aistudio, antigravity=antigravity)
    entries += [{'id': m, 'object': 'model', 'owned_by': 'remote'} for m in _remote_models(request)]
    key = getattr(request.state, 'user_key', None)
    if key and key['models']:
        entries = [entry for entry in entries if entry['id'] in key['models']]
    return JSONResponse(content={
        "object": "list",
        "data": entries,
    })


@router.get("/v1/models/{model_id:path}")
async def get_model(model_id: str, request: Request):
    key = getattr(request.state, 'user_key', None)
    if model_id not in _configured_model_ids(request) or (key and key['models'] and model_id not in key['models']):
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Model not found: {model_id}", "type": "not_found_error"}},
        )
    if model_id.startswith('remote/'):
        return JSONResponse(content={'id': model_id, 'object': 'model', 'owned_by': 'remote'})
    return JSONResponse(content=model_discovery_entry(model_id))
