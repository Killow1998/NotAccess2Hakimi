"""Operator-friendly command-line entry points for NA2H."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import secrets
import shlex
import sys
from pathlib import Path
from typing import Sequence
from urllib.parse import quote

import httpx

from hakimi_proxy import __version__
from hakimi_proxy.config import ProxyConfig, load_config, save_config
from hakimi_proxy.proxy import configure_proxy_environment
from hakimi_proxy.verification import replay_verification_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hakimi")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("generate-key", help="print a strong deployment API key")

    serve = subparsers.add_parser("serve", help="start the NA2H server")
    serve.add_argument("--config", help="path to the YAML configuration file")

    doctor = subparsers.add_parser("doctor", help="diagnose local NA2H setup")
    doctor.add_argument("--config", help="path to the YAML configuration file")
    doctor.add_argument(
        "--live",
        action="store_true",
        help="run the configured credential's explicit upstream health check",
    )
    doctor.add_argument(
        "--credential",
        metavar="PROVIDER:ID",
        help="credential to test when more than one account is configured",
    )
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    verify = subparsers.add_parser(
        "verify",
        help="run or replay the bounded Antigravity verification report",
    )
    verify.add_argument("--config", help="path to the YAML configuration file")
    verify.add_argument("--credential", help="Antigravity credential ID")
    verify.add_argument("--output", help="write the redacted report to this JSON file")
    verify.add_argument("--replay", help="validate a saved report without network access")
    verify.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def _selected_config_path(value: str | None) -> Path:
    return Path(value or os.environ.get("HAKIMI_CONFIG", "config.yaml")).expanduser().resolve()


def _new_deployment_key() -> str:
    return f"hakimi_{secrets.token_urlsafe(32)}"


def _local_base_url(host: str, port: int) -> str:
    connect_host = host.strip() or "127.0.0.1"
    if connect_host in {"0.0.0.0", "::", "[::]"}:
        connect_host = "127.0.0.1"
    elif ":" in connect_host and not connect_host.startswith("["):
        connect_host = f"[{connect_host}]"
    return f"http://{connect_host}:{port}"


def _service_snapshot(base_url: str) -> dict[str, object]:
    try:
        with httpx.Client(timeout=2.0, trust_env=False) as client:
            response = client.get(base_url + "/openapi.json")
            response.raise_for_status()
            payload = response.json()
            service = {
                "base_url": base_url,
                "running": True,
                "version": str(payload.get("info", {}).get("version", "unknown")),
            }
            try:
                ready_response = client.get(base_url + "/readyz")
                ready_payload = ready_response.json()
                service.update({
                    "ready": (
                        ready_response.status_code == 200
                        and ready_payload.get("status") == "ready"
                    ),
                    "active_credentials": int(ready_payload.get("active_credentials", 0)),
                    "total_credentials": int(ready_payload.get("total_credentials", 0)),
                })
            except (httpx.HTTPError, ValueError, TypeError):
                service.update({
                    "ready": False,
                    "active_credentials": 0,
                    "total_credentials": 0,
                })
            return service
    except (httpx.HTTPError, ValueError, TypeError):
        return {"base_url": base_url, "running": False}


def _authorization_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"} if auth_token else {}


def _safe_health_stages(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        return []
    stages = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        stages.append({
            "name": str(item.get("name", "unknown")),
            "status": str(item.get("status", "unknown")),
            "latency_ms": item.get("latency_ms", 0),
        })
    return stages


def _live_snapshot(
    base_url: str,
    auth_token: str,
    selector: str | None = None,
) -> dict[str, object]:
    headers = _authorization_headers(auth_token)
    try:
        with httpx.Client(timeout=60.0, trust_env=False) as client:
            response = client.get(base_url + "/api/credentials", headers=headers)
            response.raise_for_status()
            payload = response.json()
            candidates = [
                {"provider": provider, "credential_id": str(item["id"])}
                for provider in ("aistudio", "antigravity")
                for item in payload.get(provider, [])
                if isinstance(item, dict) and item.get("id")
            ]
            selected = None
            if selector:
                provider, separator, credential_id = selector.partition(":")
                if separator and provider in {"aistudio", "antigravity"} and credential_id:
                    selected = next(
                        (
                            candidate
                            for candidate in candidates
                            if candidate["provider"] == provider
                            and candidate["credential_id"] == credential_id
                        ),
                        None,
                    )
                if selected is None:
                    return {"status": "credential_not_found", "candidates": candidates}
            elif len(candidates) != 1:
                return {"status": "selection_required", "candidates": candidates}
            else:
                selected = candidates[0]
            credential_url = (
                f"{base_url}/api/credentials/{selected['provider']}/"
                f"{quote(selected['credential_id'], safe='')}/test"
            )
            response = client.post(credential_url, headers=headers)
            result = response.json()
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return {"status": "unavailable"}

    health = result.get("health", {}) if isinstance(result, dict) else {}
    if response.status_code != 200 or health.get("status") != "healthy":
        error = result.get("error", {}) if isinstance(result, dict) else {}
        return {
            "status": "unhealthy",
            "provider": selected["provider"],
            "credential_id": selected["credential_id"],
            "failed_stage": str(error.get("stage", "unknown")),
            "error_type": str(error.get("type", "upstream_error")),
            "stages": _safe_health_stages(health.get("stages")),
        }
    return {
        "status": "healthy",
        "provider": selected["provider"],
        "credential_id": selected["credential_id"],
        "model": str(result.get("model", "unknown")),
        "latency_ms": result.get("latency_ms", 0),
        "stages": _safe_health_stages(health.get("stages")),
    }


def _emit(report: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False))
        return
    print(f"NA2H doctor: {report['status']}")
    for check in report["checks"]:
        print(f"- {check['status']}: {check['message']}")
    for action in report["next_actions"]:
        print(f"Next: {action}")


def _doctor(args: argparse.Namespace) -> int:
    config_path = _selected_config_path(args.config)
    if not config_path.is_file():
        quoted_path = shlex.quote(str(config_path))
        report = {
            "status": "setup_required",
            "config": {"path": str(config_path), "exists": False},
            "checks": [{
                "name": "config_file",
                "status": "error",
                "message": f"Configuration file does not exist: {config_path}",
            }],
            "next_actions": [
                f"Run hakimi serve --config {quoted_path}, copy the generated "
                "deployment key from that terminal, then open "
                "http://127.0.0.1:12345 and log in"
            ],
        }
        _emit(report, as_json=args.json)
        return 1

    try:
        config = load_config(config_path)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        report = {
            "status": "invalid_config",
            "config": {"path": str(config_path), "exists": True},
            "checks": [{
                "name": "config_file",
                "status": "error",
                "message": f"Configuration could not be loaded ({type(exc).__name__})",
            }],
            "next_actions": [f"Fix {config_path}, then run hakimi doctor again"],
        }
        _emit(report, as_json=args.json)
        return 1

    aistudio_count = len(config.aistudio_credentials)
    antigravity_count = len(config.antigravity_credentials)
    credential_count = aistudio_count + antigravity_count
    proxy_source = configure_proxy_environment(config.proxy)
    base_url = _local_base_url(config.host, config.port)
    service = _service_snapshot(base_url)
    checks: list[dict[str, str]] = [{
        "name": "config_file",
        "status": "ok",
        "message": f"Loaded configuration from {config_path}",
    }]
    next_actions: list[str] = []

    if credential_count:
        checks.append({
            "name": "credentials",
            "status": "ok",
            "message": f"Found {credential_count} configured credential(s)",
        })
    else:
        checks.append({
            "name": "credentials",
            "status": "error",
            "message": "No provider credential is configured",
        })
        next_actions.append(f"Open {base_url} and add a credential")

    if service["running"]:
        checks.append({
            "name": "service",
            "status": "ok",
            "message": f"NA2H is running at {base_url}",
        })
        version_matches = service["version"] == __version__
        checks.append({
            "name": "version",
            "status": "ok" if version_matches else "error",
            "message": (
                f"Running version matches {__version__}"
                if version_matches
                else f"Running version {service['version']} does not match installed {__version__}"
            ),
        })
        if not version_matches:
            next_actions.append(
                f"Restart NA2H with hakimi serve --config {shlex.quote(str(config_path))}"
            )
        checks.append({
            "name": "readiness",
            "status": "ok" if service["ready"] else "error",
            "message": (
                f"{service['active_credentials']} credential(s) are schedulable"
                if service["ready"]
                else "The running service has no schedulable credential"
            ),
        })
        if not service["ready"]:
            next_actions.append(f"Open {base_url} and restore an active credential")
    else:
        checks.append({
            "name": "service",
            "status": "warning",
            "message": f"NA2H is not reachable at {base_url}",
        })
        next_actions.insert(
            0,
            f"Run hakimi serve --config {shlex.quote(str(config_path))}",
        )

    if not credential_count:
        status = "setup_required"
    elif not service["running"]:
        status = "service_stopped"
    elif service["version"] != __version__:
        status = "restart_required"
    elif not service["ready"]:
        status = "not_ready"
    else:
        status = "ready"
    report = {
        "status": status,
        "version": __version__,
        "config": {
            "path": str(config_path),
            "exists": True,
            "credential_counts": {
                "aistudio": aistudio_count,
                "antigravity": antigravity_count,
                "total": credential_count,
            },
            "auth_enabled": bool(config.auth_token),
            "proxy_source": proxy_source,
        },
        "service": service,
        "checks": checks,
        "next_actions": next_actions,
    }
    if args.live:
        if status != "ready":
            report["checks"].append({
                "name": "live_credential",
                "status": "error",
                "message": "Live diagnosis requires a matching ready NA2H service",
            })
        else:
            live = _live_snapshot(base_url, config.auth_token, args.credential)
            report["live"] = live
            live_ok = live["status"] == "healthy"
            report["checks"].append({
                "name": "live_credential",
                "status": "ok" if live_ok else "error",
                "message": (
                    "Credential passed local, OAuth, control-plane, and inference health"
                    if live_ok
                    else "Credential did not complete the explicit live health check"
                ),
            })
            if live_ok:
                report["status"] = "healthy"
            else:
                report["status"] = str(live["status"])
                candidates = live.get("candidates", [])
                if live["status"] == "selection_required" and candidates:
                    for candidate in candidates:
                        selector = f"{candidate['provider']}:{candidate['credential_id']}"
                        report["next_actions"].append(
                            f"Run hakimi doctor --config {shlex.quote(str(config_path))} "
                            f"--live --credential {shlex.quote(selector)}"
                        )
                else:
                    report["next_actions"].append(
                        f"Open {base_url} and inspect the credential health result"
                    )
    _emit(report, as_json=args.json)
    return 0 if report["status"] in {"ready", "healthy"} else 1


def _serve(args: argparse.Namespace) -> int:
    config_path = _selected_config_path(args.config)
    if args.config:
        os.environ["HAKIMI_CONFIG"] = str(config_path)
    config = load_config(config_path) if config_path.is_file() else ProxyConfig()
    if not config.auth_token:
        config.auth_token = _new_deployment_key()
        try:
            save_config(config, config_path)
        except OSError:
            print(
                "hakimi: could not save the generated deployment key to "
                f"{config_path}; refusing to start",
                file=sys.stderr,
            )
            return 2
        print(
            "hakimi: generated deployment API key (shown once):\n"
            f"{config.auth_token}\n"
            f"hakimi: saved to {config_path}",
            file=sys.stderr,
        )
    main_module = importlib.import_module("hakimi_proxy.main")
    main_module.main()
    return 0


def _emit_verification(report: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False))
        return
    print(f"NA2H verification: {report.get('status', 'unknown')}")
    if "report_status" in report:
        print(f"- saved report status: {report['report_status']}")
    summary = report.get("summary")
    if isinstance(summary, dict):
        print(f"- inference requests: {summary.get('inference_requests', 0)}")
        print(f"- leaked leases: {summary.get('leaked_leases', 0)}")


def _write_private_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        path.chmod(0o600)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _verify(args: argparse.Namespace) -> int:
    if args.replay:
        try:
            payload = json.loads(
                Path(args.replay).expanduser().read_text(encoding="utf-8")
            )
            if not isinstance(payload, dict):
                raise ValueError("verification report must be an object")
            result = replay_verification_report(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            result = {"status": "invalid", "error_type": type(exc).__name__}
            _emit_verification(result, as_json=args.json)
            return 1
        _emit_verification(result, as_json=args.json)
        return 0

    config_path = _selected_config_path(args.config)
    try:
        config = load_config(config_path)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        result = {"status": "invalid_config", "error_type": type(exc).__name__}
        _emit_verification(result, as_json=args.json)
        return 1

    base_url = _local_base_url(config.host, config.port)
    headers = _authorization_headers(config.auth_token)
    try:
        with httpx.Client(timeout=180.0, trust_env=False) as client:
            response = client.get(base_url + "/api/credentials", headers=headers)
            response.raise_for_status()
            payload = response.json()
            candidates = [
                str(item["id"])
                for item in payload.get("antigravity", [])
                if isinstance(item, dict) and item.get("id")
            ]
            selector = args.credential or ""
            if selector.startswith("antigravity:"):
                selector = selector.partition(":")[2]
            if selector:
                selected = selector if selector in candidates else None
            else:
                selected = candidates[0] if len(candidates) == 1 else None
            if selected is None:
                result = {
                    "status": "selection_required",
                    "candidate_count": len(candidates),
                }
                _emit_verification(result, as_json=args.json)
                return 1
            response = client.post(
                f"{base_url}/api/credentials/antigravity/"
                f"{quote(selected, safe='')}/verify",
                headers=headers,
            )
            report = response.json()
            if response.status_code != 200 or not isinstance(report, dict):
                result = {"status": "unavailable", "http_status": response.status_code}
                _emit_verification(result, as_json=args.json)
                return 1
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        result = {"status": "unavailable", "error_type": type(exc).__name__}
        _emit_verification(result, as_json=args.json)
        return 1

    if args.output:
        try:
            _write_private_report(Path(args.output).expanduser(), report)
        except OSError as exc:
            result = {"status": "write_failed", "error_type": type(exc).__name__}
            _emit_verification(result, as_json=args.json)
            return 1
    _emit_verification(report, as_json=args.json)
    return 0 if report.get("status") == "passed" else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the public `hakimi` command."""
    args = _build_parser().parse_args(argv)
    if args.command == "generate-key":
        print(_new_deployment_key())
        return 0
    if args.command == "serve":
        return _serve(args)
    if args.command == "doctor":
        return _doctor(args)
    if args.command == "verify":
        return _verify(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
