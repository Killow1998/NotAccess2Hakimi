"""Versioned credential portability without runtime token leakage."""

import pytest

from hakimi_proxy.config import AIStudioCredential, AntigravityCredential, ProxyConfig
from hakimi_proxy.credential_bundle import (
    CredentialBundleError,
    build_credential_bundle,
    merge_credential_bundle,
    parse_credential_bundle,
    plan_credential_import,
)


def _config() -> ProxyConfig:
    return ProxyConfig(
        auth_token="downstream-secret",
        proxy="socks5://proxy-secret",
        aistudio_credentials=[
            AIStudioCredential(id="ai-existing", api_key="ai-secret", project="p1"),
        ],
        antigravity_credentials=[
            AntigravityCredential(
                id="ag-existing",
                client_id="client-id",
                client_secret="client-secret",
                refresh_token="refresh-secret",
                access_token="short-lived-access",
                expires_at=123.0,
                project="ag-project",
            ),
        ],
    )


def test_bundle_exports_only_portable_credentials():
    bundle = build_credential_bundle(_config())

    assert bundle["format"] == "notaccess2hakimi.credentials"
    assert bundle["version"] == 1
    assert bundle["aistudio"][0]["api_key"] == "ai-secret"
    assert bundle["antigravity"][0]["refresh_token"] == "refresh-secret"
    rendered = str(bundle)
    assert "short-lived-access" not in rendered
    assert "downstream-secret" not in rendered
    assert "proxy-secret" not in rendered
    assert "expires_at" not in rendered


def test_bundle_parser_rejects_unknown_version_and_duplicate_ids():
    with pytest.raises(CredentialBundleError, match="Unsupported credential bundle"):
        parse_credential_bundle({"format": "notaccess2hakimi.credentials", "version": 2})

    with pytest.raises(CredentialBundleError, match="Duplicate aistudio credential ID"):
        parse_credential_bundle({
            "format": "notaccess2hakimi.credentials",
            "version": 1,
            "aistudio": [
                {"id": "same", "api_key": "one"},
                {"id": "same", "api_key": "two"},
            ],
            "antigravity": [],
        })


def test_import_plan_and_merge_make_conflicts_explicit():
    config = _config()
    parsed = parse_credential_bundle({
        "format": "notaccess2hakimi.credentials",
        "version": 1,
        "aistudio": [
            {"id": "ai-existing", "api_key": "replacement"},
            {"id": "ai-new", "api_key": "new-secret"},
        ],
        "antigravity": [{
            "id": "ag-new",
            "client_id": "cid",
            "client_secret": "csecret",
            "refresh_token": "refresh",
        }],
    })

    plan = plan_credential_import(config, parsed)
    assert plan["total_new"] == 2
    assert plan["total_conflicts"] == 1
    assert plan["conflicts"] == [{"kind": "aistudio", "id": "ai-existing"}]

    ai, ag, result = merge_credential_bundle(config, parsed, conflict="skip")
    assert [item.id for item in ai] == ["ai-existing", "ai-new"]
    assert next(item for item in ai if item.id == "ai-existing").api_key == "ai-secret"
    assert [item.id for item in ag] == ["ag-existing", "ag-new"]
    assert result == {"imported": 2, "overwritten": 0, "skipped": 1}

    ai, _, result = merge_credential_bundle(config, parsed, conflict="overwrite")
    assert next(item for item in ai if item.id == "ai-existing").api_key == "replacement"
    assert result == {"imported": 2, "overwritten": 1, "skipped": 0}
