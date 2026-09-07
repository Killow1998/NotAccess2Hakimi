"""Configuration loading for hakimi-proxy."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from urllib.parse import urlsplit


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
    account: str = ""
    access_token: str = ""
    expires_at: float = 0.0
    project: str = ""
    auto_onboard: bool = False


@dataclass
class RemoteCredential:
    id: str
    group: str
    base_url: str
    api_key: str
    models: list[str]
    account: str = ''

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if (url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in {'localhost', '127.0.0.1', '::1'})) or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Remote base_url must use HTTPS (HTTP is allowed on loopback only) without URL credentials, query or fragment')
        if not self.group or not all(c.isalnum() or c in '-_' for c in self.group):
            raise ValueError('Remote group must contain only letters, digits, hyphens or underscores')
        if not isinstance(self.models, list) or not self.models or any(not isinstance(m, str) or not m for m in self.models):
            raise ValueError('Remote models must be a nonempty list of model IDs')


@dataclass
class ProxyConfig:
    host: str = "127.0.0.1"
    port: int = 12345
    auth_token: str = ""
    max_retries: int = 3
    cooldown_seconds: int = 60
    db_path: str = "hakimi.db"
    proxy: str = ""
    # Application-level Antigravity OAuth client settings. These are kept
    # separate from per-account credentials and are never returned by admin
    # API responses.
    antigravity_client_id: str = ""
    antigravity_client_secret: str = ""
    aistudio_credentials: list[AIStudioCredential] = field(default_factory=list)
    antigravity_credentials: list[AntigravityCredential] = field(default_factory=list)
    remote_credentials: list[RemoteCredential] = field(default_factory=list)


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
                account=item.get("account", ""),
                access_token=item.get("access_token", ""),
                expires_at=item.get("expires_at", 0.0),
                project=item.get("project", item.get("project_id", "")),
                auto_onboard=item.get("auto_onboard", False),
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
        antigravity_client_id=raw.get("antigravity_client_id", ""),
        antigravity_client_secret=raw.get("antigravity_client_secret", ""),
        aistudio_credentials=ai_creds,
        antigravity_credentials=ag_creds,
        remote_credentials=[RemoteCredential(**item) for item in raw.get('remotes', [])],
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
        "antigravity_client_id": config.antigravity_client_id,
        "antigravity_client_secret": config.antigravity_client_secret,
        "remotes": [dict(id=c.id, group=c.group, base_url=c.base_url, api_key=c.api_key,
                         models=c.models, account=c.account) for c in config.remote_credentials],
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
                "account": c.account,
                "access_token": c.access_token,
                "expires_at": c.expires_at,
                "project": c.project,
                "auto_onboard": c.auto_onboard,
            }
            for c in config.antigravity_credentials
        ],
    }
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def get_config_path() -> str:
    """Return the active config file path."""
    return os.environ.get("HAKIMI_CONFIG", "config.yaml")
