"""Select an explicit, environment, or desktop network proxy."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from typing import Any
from urllib.parse import urlparse
from urllib.request import getproxies

PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _gsettings_value(schema: str, key: str) -> Any:
    try:
        result = subprocess.run(
            ["gsettings", "get", schema, key],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    value = result.stdout.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return None


def _proxy_url(host: Any, port: Any, scheme: str) -> str:
    if not isinstance(host, str) or not host.strip():
        return ""
    host = host.strip()
    if any(character.isspace() or character in "/@?#" for character in host):
        return ""
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return ""
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    return f"{scheme}://{host}:{port}"


def _gnome_proxy_settings() -> dict[str, Any]:
    if not sys.platform.startswith("linux"):
        return {}
    root = "org.gnome.system.proxy"
    if _gsettings_value(root, "mode") != "manual":
        return {}
    http = _proxy_url(
        _gsettings_value(root + ".http", "host"),
        _gsettings_value(root + ".http", "port"),
        "http",
    )
    https = _proxy_url(
        _gsettings_value(root + ".https", "host"),
        _gsettings_value(root + ".https", "port"),
        "http",
    )
    if not https and _gsettings_value(root, "use-same-proxy") is True:
        https = http
    socks = _proxy_url(
        _gsettings_value(root + ".socks", "host"),
        _gsettings_value(root + ".socks", "port"),
        "socks5",
    )
    ignored = _gsettings_value(root, "ignore-hosts")
    return {
        "http": http,
        "https": https,
        "all": socks,
        "no": ",".join(item for item in ignored if isinstance(item, str))
        if isinstance(ignored, list)
        else "",
    }


def _apply_proxy_settings(settings: dict[str, Any]) -> bool:
    applied = False
    for scheme in ("http", "https", "all"):
        value = settings.get(scheme)
        if not isinstance(value, str) or not value:
            continue
        parsed = urlparse(value)
        try:
            valid = parsed.scheme in ("http", "https", "socks5", "socks5h") and bool(
                parsed.hostname and parsed.port
            )
        except ValueError:
            valid = False
        if not valid:
            continue
        os.environ.setdefault(scheme + "_proxy", value)
        os.environ.setdefault(scheme.upper() + "_PROXY", value)
        applied = True
    ignored = settings.get("no")
    if applied and isinstance(ignored, str) and ignored:
        os.environ.setdefault("no_proxy", ignored)
        os.environ.setdefault("NO_PROXY", ignored)
    return applied


def configure_proxy_environment(explicit_proxy: str = "") -> str:
    """Apply the first available proxy source and return its source label."""
    if explicit_proxy.strip():
        return "config"
    if any(os.environ.get(key) for key in PROXY_ENV_KEYS):
        return "environment"
    if _apply_proxy_settings(getproxies()):
        return "system"
    if _apply_proxy_settings(_gnome_proxy_settings()):
        return "system"
    return "direct"
