"""Bounded public-API reliability gate using fake upstream responses only."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from hakimi_proxy.config import AIStudioCredential, ProxyConfig, save_config

MAX_REQUESTS = 10_000
MAX_CONCURRENCY = 64


def _success_response(text: str = "OK") -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://fake-upstream.invalid"),
        json={
            "id": "chatcmpl-reliability-gate",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def _build_app(root: Path, name: str, credential_count: int):
    config_path = root / f"{name}.yaml"
    save_config(
        ProxyConfig(
            max_retries=3,
            cooldown_seconds=60,
            db_path=str(root / f"{name}.db"),
            aistudio_credentials=[
                AIStudioCredential(id=f"{name}-{index}", api_key="fake-key")
                for index in range(credential_count)
            ],
        ),
        config_path,
    )
    os.environ["HAKIMI_CONFIG"] = str(config_path)
    # Import only after the private fake config and working directory exist.
    from hakimi_proxy.main import create_app

    return create_app()


async def _request(app, method: str, path: str, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://reliability-gate",
    ) as client:
        return await client.request(method, path, **kwargs)


async def _success_load(root: Path, requests: int, concurrency: int) -> dict[str, int]:
    app = _build_app(root, "success", 1)
    active = 0
    max_active = 0

    async def forward(body, cred, stream, client):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.001)
            return _success_response()
        finally:
            active -= 1

    app.state.aistudio.forward = forward
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://reliability-gate",
    ) as client:
        async def one(index: int) -> None:
            async with semaphore:
                response = await client.post("/v1/responses", json={
                    "model": "gemini-3.7-flash",
                    "input": f"reliability-{index}",
                })
                if response.status_code != 200 or response.json().get("output_text") != "OK":
                    raise RuntimeError(f"success path failed with HTTP {response.status_code}")

        await asyncio.gather(*(one(index) for index in range(requests)))
        readiness = await client.get("/readyz")

    leaked = sum(item["in_flight"] for item in app.state.pool.get_status())
    return {
        "successes": requests,
        "max_active_upstream": max_active,
        "leaked_leases": leaked,
        "readiness_status": readiness.status_code,
    }


async def _fault_case(
    root: Path,
    name: str,
    credential_count: int,
    forward: Callable[..., Any],
) -> httpx.Response:
    app = _build_app(root, name, credential_count)
    app.state.aistudio.forward = forward
    return await _request(app, "POST", "/v1/responses", json={
        "model": "gemini-3.7-flash",
        "input": name,
    })


async def _fault_matrix(root: Path) -> dict[str, dict[str, Any]]:
    calls = 0

    async def rate_limit_then_succeed(body, cred, stream, client):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                request=httpx.Request("POST", "https://fake-upstream.invalid"),
                headers={"retry-after": "60"},
                json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "fake rate limit"}},
            )
        return _success_response()

    rate_limit = await _fault_case(root, "rate-limit", 2, rate_limit_then_succeed)

    async def server_error(body, cred, stream, client):
        return httpx.Response(
            503,
            request=httpx.Request("POST", "https://fake-upstream.invalid"),
            json={"error": {"status": "UNAVAILABLE", "message": "fake outage"}},
        )

    unavailable = await _fault_case(root, "upstream-503", 1, server_error)

    async def timeout(body, cred, stream, client):
        raise httpx.ConnectTimeout(
            "fake timeout",
            request=httpx.Request("POST", "https://fake-upstream.invalid"),
        )

    timed_out = await _fault_case(root, "timeout", 1, timeout)
    return {
        "rate_limit_failover": {"http_status": rate_limit.status_code, "calls": calls},
        "upstream_503": {
            "http_status": unavailable.status_code,
            "error_type": unavailable.json().get("error", {}).get("type"),
        },
        "timeout": {
            "http_status": timed_out.status_code,
            "error_type": timed_out.json().get("error", {}).get("type"),
        },
    }


def _validate(result: dict[str, Any]) -> None:
    expected_faults = {
        "rate_limit_failover": {"http_status": 200, "calls": 2},
        "upstream_503": {"http_status": 503, "error_type": "upstream_server_error"},
        "timeout": {"http_status": 503, "error_type": "upstream_transport_error"},
    }
    if result["successes"] != result["requests"]:
        raise RuntimeError("not every success-path request completed")
    if result["max_active_upstream"] != 1:
        raise RuntimeError("single-flight invariant was violated")
    if result["leaked_leases"] != 0:
        raise RuntimeError("credential lease leaked after load")
    if result["readiness_status"] != 200:
        raise RuntimeError("ready pool did not report HTTP 200")
    if result["faults"] != expected_faults:
        raise RuntimeError("fault matrix did not preserve the public error contract")


async def run_gate(*, requests: int = 500, concurrency: int = 8) -> dict[str, Any]:
    """Run a bounded reliability check without reading real credentials or using network I/O."""
    if not 1 <= requests <= MAX_REQUESTS:
        raise ValueError(f"requests must be between 1 and {MAX_REQUESTS}")
    if not 1 <= concurrency <= MAX_CONCURRENCY:
        raise ValueError(f"concurrency must be between 1 and {MAX_CONCURRENCY}")
    concurrency = min(concurrency, requests)
    started = time.perf_counter()
    previous_config = os.environ.get("HAKIMI_CONFIG")
    previous_cwd = Path.cwd()
    try:
        with tempfile.TemporaryDirectory(prefix="na2h-reliability-") as temp_dir:
            root = Path(temp_dir)
            os.chdir(root)
            result: dict[str, Any] = {
                "requests": requests,
                "concurrency": concurrency,
                **await _success_load(root, requests, concurrency),
                "faults": await _fault_matrix(root),
            }
    finally:
        os.chdir(previous_cwd)
        if previous_config is None:
            os.environ.pop("HAKIMI_CONFIG", None)
        else:
            os.environ["HAKIMI_CONFIG"] = previous_config

    result["duration_ms"] = round((time.perf_counter() - started) * 1000)
    _validate(result)
    result["status"] = "passed"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args(argv)
    # Keep the command's stdout useful for automation: application/httpx INFO
    # logs would otherwise emit one line per synthetic request.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("hakimi_proxy").setLevel(logging.WARNING)
    try:
        result = asyncio.run(run_gate(requests=args.requests, concurrency=args.concurrency))
    except Exception as exc:
        print(json.dumps({
            "status": "failed",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
