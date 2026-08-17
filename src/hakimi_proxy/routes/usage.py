"""GET /v1/usage and /v1/usage/export routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/v1/usage")
async def get_usage(request: Request):
    """Aggregated usage by credential x model x day."""
    store = request.app.state.store
    credential_id = request.query_params.get("credential_id")
    model = request.query_params.get("model")
    start_date = request.query_params.get("start_date")
    end_date = request.query_params.get("end_date")

    rows = store.get_usage(
        credential_id=credential_id,
        model=model,
        start_date=start_date,
        end_date=end_date,
    )

    # Summary totals
    total_cost = sum(r.get("cost_usd", 0) for r in rows)
    total_requests = sum(r.get("request_count", 0) for r in rows)
    total_input = sum(r.get("input_tokens", 0) for r in rows)
    total_output = sum(r.get("output_tokens", 0) for r in rows)

    return JSONResponse(content={
        "summary": {
            "total_cost_usd": round(total_cost, 6),
            "total_requests": total_requests,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
        },
        "records": rows,
    })


@router.get("/v1/usage/export")
async def export_usage(request: Request):
    """Individual usage log entries."""
    store = request.app.state.store
    credential_id = request.query_params.get("credential_id")
    model = request.query_params.get("model")
    start_date = request.query_params.get("start_date")
    end_date = request.query_params.get("end_date")
    limit = int(request.query_params.get("limit", "1000"))

    rows = store.get_usage_log(
        credential_id=credential_id,
        model=model,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return JSONResponse(content={"records": rows})


@router.get("/v1/credentials")
async def get_credentials(request: Request):
    """Credential pool status."""
    pool = request.app.state.pool
    return JSONResponse(content={"credentials": pool.get_status()})
