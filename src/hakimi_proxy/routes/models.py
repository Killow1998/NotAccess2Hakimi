"""GET /v1/models route."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from hakimi_proxy.adapters.aistudio import SUPPORTED_MODELS as AISTUDIO_MODELS
from hakimi_proxy.adapters.antigravity import SUPPORTED_MODELS as ANTIGRAVITY_MODELS

router = APIRouter()


@router.get("/v1/models")
async def list_models(request: Request):
    all_models = sorted(AISTUDIO_MODELS | ANTIGRAVITY_MODELS)
    data = [
        {"id": m, "object": "model", "created": 0, "owned_by": "google"}
        for m in all_models
    ]
    return JSONResponse(content={"object": "list", "data": data})


@router.get("/v1/models/{model_id}")
async def get_model(model_id: str):
    return JSONResponse(content={"id": model_id, "object": "model", "created": 0, "owned_by": "google"})
