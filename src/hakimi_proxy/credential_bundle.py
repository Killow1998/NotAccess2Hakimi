"""Versioned credential-only backup and restore helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from hakimi_proxy.config import AIStudioCredential, AntigravityCredential, ProxyConfig

BUNDLE_FORMAT = "notaccess2hakimi.credentials"
BUNDLE_VERSION = 1
MAX_CREDENTIALS_PER_KIND = 256


class CredentialBundleError(ValueError):
    """A portable credential bundle failed structural validation."""


@dataclass(frozen=True)
class ParsedCredentialBundle:
    aistudio: list[AIStudioCredential]
    antigravity: list[AntigravityCredential]


def build_credential_bundle(config: ProxyConfig) -> dict[str, Any]:
    """Return portable long-lived credentials without runtime/config secrets."""
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "aistudio": [
            {
                "id": credential.id,
                "api_key": credential.api_key,
                "project": credential.project,
                "account": credential.account,
            }
            for credential in config.aistudio_credentials
        ],
        "antigravity": [
            {
                "id": credential.id,
                "client_id": credential.client_id,
                "client_secret": credential.client_secret,
                "refresh_token": credential.refresh_token,
                "account": credential.account,
                "project": credential.project,
                "auto_onboard": credential.auto_onboard,
            }
            for credential in config.antigravity_credentials
        ],
    }


def _items(raw: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    value = raw.get(kind, [])
    if not isinstance(value, list):
        raise CredentialBundleError(f"Credential bundle field '{kind}' must be a list")
    if len(value) > MAX_CREDENTIALS_PER_KIND:
        raise CredentialBundleError(f"Credential bundle contains too many {kind} credentials")
    if not all(isinstance(item, dict) for item in value):
        raise CredentialBundleError(f"Credential bundle field '{kind}' contains an invalid item")
    return value


def _text(
    item: dict[str, Any],
    field: str,
    *,
    required: bool = False,
    max_length: int = 8192,
) -> str:
    value = item.get(field, "")
    if not isinstance(value, str):
        raise CredentialBundleError(f"Credential field '{field}' must be text")
    value = value.strip()
    if required and not value:
        raise CredentialBundleError(f"Credential field '{field}' is required")
    if len(value) > max_length:
        raise CredentialBundleError(f"Credential field '{field}' is too long")
    return value


def _unique_ids(items: list[Any], kind: str) -> None:
    seen: set[str] = set()
    for credential in items:
        if credential.id in seen:
            raise CredentialBundleError(f"Duplicate {kind} credential ID: {credential.id}")
        seen.add(credential.id)


def parse_credential_bundle(raw: Any) -> ParsedCredentialBundle:
    """Validate an untrusted bundle and construct fresh credential objects."""
    if not isinstance(raw, dict):
        raise CredentialBundleError("Credential bundle must be a JSON object")
    if raw.get("format") != BUNDLE_FORMAT or raw.get("version") != BUNDLE_VERSION:
        raise CredentialBundleError("Unsupported credential bundle format or version")

    aistudio = [
        AIStudioCredential(
            id=_text(item, "id", required=True, max_length=128),
            api_key=_text(item, "api_key", required=True),
            project=_text(item, "project", max_length=512),
            account=_text(item, "account", max_length=512),
        )
        for item in _items(raw, "aistudio")
    ]

    antigravity: list[AntigravityCredential] = []
    for item in _items(raw, "antigravity"):
        auto_onboard = item.get("auto_onboard", False)
        if not isinstance(auto_onboard, bool):
            raise CredentialBundleError("Credential field 'auto_onboard' must be boolean")
        antigravity.append(AntigravityCredential(
            id=_text(item, "id", required=True, max_length=128),
            client_id=_text(item, "client_id", required=True),
            client_secret=_text(item, "client_secret", required=True),
            refresh_token=_text(item, "refresh_token", required=True),
            account=_text(item, "account", max_length=512),
            project=_text(item, "project", max_length=512),
            auto_onboard=auto_onboard,
        ))

    _unique_ids(aistudio, "aistudio")
    _unique_ids(antigravity, "antigravity")
    return ParsedCredentialBundle(aistudio=aistudio, antigravity=antigravity)


def plan_credential_import(
    config: ProxyConfig,
    bundle: ParsedCredentialBundle,
) -> dict[str, Any]:
    """Describe new and conflicting IDs without exposing credential values."""
    existing = {
        "aistudio": {item.id for item in config.aistudio_credentials},
        "antigravity": {item.id for item in config.antigravity_credentials},
    }
    incoming = {
        "aistudio": bundle.aistudio,
        "antigravity": bundle.antigravity,
    }
    conflicts: list[dict[str, str]] = []
    counts: dict[str, dict[str, int]] = {}
    for kind, credentials in incoming.items():
        conflict_ids = [item.id for item in credentials if item.id in existing[kind]]
        conflicts.extend({"kind": kind, "id": item_id} for item_id in conflict_ids)
        counts[kind] = {
            "new": len(credentials) - len(conflict_ids),
            "conflicts": len(conflict_ids),
        }
    return {
        **counts,
        "total_new": sum(item["new"] for item in counts.values()),
        "total_conflicts": len(conflicts),
        "conflicts": conflicts,
    }


def merge_credential_bundle(
    config: ProxyConfig,
    bundle: ParsedCredentialBundle,
    *,
    conflict: Literal["skip", "overwrite"] = "skip",
) -> tuple[list[AIStudioCredential], list[AntigravityCredential], dict[str, int]]:
    """Build replacement lists without mutating config until persistence is ready."""
    if conflict not in {"skip", "overwrite"}:
        raise CredentialBundleError("Import conflict policy must be 'skip' or 'overwrite'")

    result = {"imported": 0, "overwritten": 0, "skipped": 0}

    def merge(existing: list[Any], incoming: list[Any]) -> list[Any]:
        merged = list(existing)
        indexes = {item.id: index for index, item in enumerate(merged)}
        for item in incoming:
            index = indexes.get(item.id)
            if index is None:
                indexes[item.id] = len(merged)
                merged.append(item)
                result["imported"] += 1
            elif conflict == "overwrite":
                merged[index] = item
                result["overwritten"] += 1
            else:
                result["skipped"] += 1
        return merged

    return (
        merge(config.aistudio_credentials, bundle.aistudio),
        merge(config.antigravity_credentials, bundle.antigravity),
        result,
    )
