"""GET /v1/models route."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from hakimi_proxy.model_catalog import ALL_MODELS, list_model_discovery_entries, model_discovery_entry

router = APIRouter()


@router.get("/v1/models")
async def list_models(request: Request):
    return JSONResponse(content={"object": "list", "data": list_model_discovery_entries()})


@router.get("/v1/models/{model_id}")
async def get_model(model_id: str):
    if model_id not in ALL_MODELS:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Model not found: {model_id}", "type": "not_found_error"}},
        )
    return JSONResponse(content=model_discovery_entry(model_id))
