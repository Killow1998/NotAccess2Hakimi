# Changelog

All notable changes to NotAccess2Hakimi are documented here.

## [0.3.0] - 2026-08-27

### Added

- One Antigravity login action that selects local automatic callback on
  loopback and listener-free copy/paste completion on domain or IP access.
- Versioned credential backup/restore with preview, explicit conflict policy,
  no-store responses, and HTTPS-or-loopback enforcement.
- A layered manual account check covering local configuration, OAuth refresh,
  `loadCodeAssist`, and real inference with per-stage latency/failure reporting.

### Security

- Credential bundles exclude short-lived access tokens, proxy settings,
  downstream Bearer auth, runtime state, and usage records.
- Remote plaintext HTTP cannot use credential import/export, and no background
  OAuth keepalive, generation probe, or quota polling was added.

### Verified

- Added socket-free remote OAuth, bundle validation/round-trip, transport,
  conflict, staged health, and control-plane failure regressions.
- Passed a live authorized Antigravity check across local configuration, OAuth
  refresh, `loadCodeAssist`, and real inference.

## [0.2.1] - 2026-08-27

### Fixed

- Mark synthetic or migrated Gemini tool history when the original thought
  signature is unavailable, while preserving native signatures and leaving
  later parallel calls unsigned.
- Buffer bounded streamed error bodies before classification so upstream 400
  details surface as a 502 request error instead of an internal
  `ResponseNotRead` 500.

### Verified

- Reproduced the failing Codex session boundary and covered unsigned Responses
  custom-tool replay, native signatures, parallel calls, and streamed 400s.
- Completed a live authorized Codex session across model switches, compaction,
  resume, image input, repeated custom-tool calls, and tool-result replay.

## [0.2.0] - 2026-08-27

### Added

- Central model catalog shared by both adapters and `/v1/models`.
- Generic capability metadata for context/output limits, reasoning levels,
  input/output modalities, tools, structured output, streaming, protocols, and
  per-field provenance; unknown model facts remain explicitly unknown.
- A model catalog and EMP External Provider integration section in the existing
  zero-build Web UI, including copy actions that never expose the Bearer token.
- A private, allowlisted JSONL diagnostic journal with bounded rotation and
  safe health-status reporting.

### Changed

- Normal `python -m hakimi_proxy.main` startup now runs the prebuilt app once
  without implicit hot reload. Development reload is an explicit uv-only
  Uvicorn command that excludes local config, state, and database files.
- Application, package, and lockfile versions now report `0.2.0` consistently.

### Verified

- NA2H model discovery is parsed by EMP's real generic discovery implementation
  with the Antigravity tiered context, reasoning, and modality metadata intact.

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
