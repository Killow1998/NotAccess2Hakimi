"""Configuration loading for hakimi-proxy."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AIStudioCredential:
    id: str
    api_key: str
    project: str = ""
    account: str = ""


@dataclass
class AntigravityCredential:
    id: str
    client_id: str
    client_secret: str
    refresh_token: str
    access_token: str = ""
    expires_at: float = 0.0


@dataclass
class ProxyConfig:
    host: str = "127.0.0.1"
    port: int = 12345
    auth_token: str = ""
    max_retries: int = 3
    cooldown_seconds: int = 60
    db_path: str = "hakimi.db"
    proxy: str = ""
    aistudio_credentials: list[AIStudioCredential] = field(default_factory=list)
    antigravity_credentials: list[AntigravityCredential] = field(default_factory=list)


def load_config(path: str | Path) -> ProxyConfig:
    """Load proxy configuration from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    ai_creds: list[AIStudioCredential] = []
    for item in raw.get("aistudio", []):
        ai_creds.append(
            AIStudioCredential(
                id=item["id"],
                api_key=item["api_key"],
                project=item.get("project", ""),
                account=item.get("account", ""),
            )
        )

    ag_creds: list[AntigravityCredential] = []
    for item in raw.get("antigravity", []):
        ag_creds.append(
            AntigravityCredential(
                id=item["id"],
                client_id=item["client_id"],
                client_secret=item["client_secret"],
                refresh_token=item["refresh_token"],
                access_token=item.get("access_token", ""),
                expires_at=item.get("expires_at", 0.0),
            )
        )

    return ProxyConfig(
        host=raw.get("host", "127.0.0.1"),
        port=raw.get("port", 12345),
        auth_token=raw.get("auth_token", ""),
        max_retries=raw.get("max_retries", 3),
        cooldown_seconds=raw.get("cooldown_seconds", 60),
        db_path=raw.get("db_path", "hakimi.db"),
        proxy=raw.get("proxy", ""),
        aistudio_credentials=ai_creds,
        antigravity_credentials=ag_creds,
    )


def load_config_from_env() -> ProxyConfig:
    """Load config from HAKIMI_CONFIG env var, or return a minimal default."""
    config_path = os.environ.get("HAKIMI_CONFIG", "config.yaml")
    if os.path.exists(config_path):
        return load_config(config_path)
    return ProxyConfig()


def save_config(config: ProxyConfig, path: str | Path | None = None) -> None:
    """Persist config back to a YAML file."""
    path = Path(path or os.environ.get("HAKIMI_CONFIG", "config.yaml"))
    raw: dict[str, Any] = {
        "host": config.host,
        "port": config.port,
        "auth_token": config.auth_token,
        "max_retries": config.max_retries,
        "cooldown_seconds": config.cooldown_seconds,
        "db_path": config.db_path,
        "proxy": config.proxy,
        "aistudio": [
            {
                "id": c.id,
                "api_key": c.api_key,
                "project": c.project,
                "account": c.account,
            }
            for c in config.aistudio_credentials
        ],
        "antigravity": [
            {
                "id": c.id,
                "client_id": c.client_id,
                "client_secret": c.client_secret,
                "refresh_token": c.refresh_token,
                "access_token": c.access_token,
                "expires_at": c.expires_at,
            }
            for c in config.antigravity_credentials
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def get_config_path() -> str:
    """Return the active config file path."""
    return os.environ.get("HAKIMI_CONFIG", "config.yaml")
