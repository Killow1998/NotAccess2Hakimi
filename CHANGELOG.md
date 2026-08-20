# Changelog

All notable changes to NotAccess2Hakimi are documented here.

## [0.1.1] - 2026-08-20

### Fixed

- Normalize Responses `custom_tool_call` item IDs to the required `ctc_*`
  prefix while preserving the original `call_id` for tool-result pairing.
- Apply the same ID rule to streaming custom-tool output.
- Keep ordinary `function_call` IDs unchanged.

## [0.1.0] - 2026-08-20

First usable local release.

### Added

- OpenAI-compatible `/v1/chat/completions` and Codex-compatible `/v1/responses`.
- AI Studio API-key and Antigravity OAuth upstream adapters.
- Browser OAuth login with local and remote callback completion.
- Credential pooling with single-flight leases, bounded waiting, cooldown, and failover.
- Streaming and non-streaming tool-call compatibility, including Antigravity thought signatures.
- SQLite usage metering, cost estimation, bearer authentication, proxy auto-detection, and a single-page Web UI.

### Changed

- Standardized development and runtime instructions on `uv`; removed the tracked mise configuration.
- Set the default local development port to `12345` and keep the Web UI test result visible after refresh.
- Removed deprecated Gemini 2.x IDs from the default model discovery list.
- Added safe upstream error classification, runtime credential health, and actionable UI status.
- Preserved secrets in local mode-0600 config files and excluded local databases/configs from Git.

### Scope

- Designed for one local operator and one Uvicorn worker.
- Quota dashboards, virtual keys, multi-user isolation, and distributed coordination are intentionally deferred.

### Verification

- 117 automated tests pass.
- Python compilation, inline Web UI JavaScript parsing, and `git diff --check` pass.
