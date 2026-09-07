# Changelog

All notable changes to NotAccess2Hakimi are documented here.

## [Unreleased]

### Added

- User API keys separated from administrator access, model permissions,
  per-key concurrency and persistent minute/day request budgets.
- Per-user metered token usage and immediate key disablement.
- Grouped remote OpenAI Chat-compatible gateways with explicit model mapping,
  credential leases, cooldown and failover through the existing streaming pipeline.
- Web controls for user keys and remote gateways, plus deployment guidance.

- Added Gemini 3.8 Flash discovery, Antigravity tiered routing, Codex/EMP
  integration metadata, and current official pricing.
- Added PKCE-based listener-free Antigravity OAuth so Google login can happen
  on another device without installing `agy` or configuring a client secret on
  the NA2H host.

- A manual, per-account Antigravity full verification that composes local
  setup, OAuth, control-plane, quota, non-streaming Responses, and a streamed
  signed two-turn Agent replay in exactly three inference requests.
- `hakimi verify` for authenticated loopback execution, mode-0600 report output,
  and network-free structural replay of saved reports.
- An inline Web credential-card action with an explicit inference-cost warning
  and client-side download of the redacted report.
- Complete Simplified Chinese and English Web UI copy, including dynamic
  credential, quota, verification, OAuth, migration, usage, and settings states.
- Persisted system, light, and dark Web themes, available before and after
  authentication; system is the default.
- A manual Antigravity quota refresh on each credential card, backed primarily
  by the upstream Gemini shared-pool 5h and Weekly/7d windows and an in-memory
  last-successful snapshot. Page loads never poll Google.
- Cached-input, cache-write, and reasoning-token totals in the usage APIs and
  dashboard, including detailed usage fields in Chat and Responses output.

### Fixed

- Public OAuth clients can export and restore credentials and refresh tokens
  without a client secret. Manual credential editing can explicitly clear a secret.
- Keep OAuth client IDs and secrets paired across configuration reloads, and use
  the original client identity when completing an authorization already in progress.
- Preserve account leases, cooldowns, and disabled states when settings change.
  Replacing or deleting a busy credential now waits for the user to retry after
  active requests finish, without changing the saved configuration on rejection.
- Finish connection cleanup and release account leases even after repeated
  cancellation; do not report truncated or invalid tool arguments as successful.
- Keep streamed tool identities consistent when their names or IDs arrive late.
- Restore the working directory before cleaning up reliability-test files on Windows.

- API-equivalent cost estimation for routed Antigravity tier IDs such as
  `gemini-3.7-flash-tiered`, including cached-input and thinking-token prices.
- Quota lookup failures no longer disturb inference health or erase the last
  successful quota snapshot.
- Full-verification stages fail when visible response text, a function call,
  thought-signature carrier, final Agent message, or selected-account lease
  cleanup is missing.
- The live full-verification tool stage now uses its own instruction and an
  explicit first-turn `list_files` choice instead of reusing the text probe and
  allowing the model to skip the function call.
- Bounded verification stream consumption closes its iterator on early exit,
  so the byte limit cannot leave a credential lease suspended.
- Offline verification replay rejects non-object stages through its normal
  invalid-report path instead of crashing or accepting malformed failed reports.

### Security

- Verification reports use an allowlist of stage/status/latency, safe error
  metadata, and protocol structure only. Prompts, outputs, OAuth values,
  provider messages, call IDs, thought signatures, project IDs, proxy URLs,
  and deployment keys are never retained.

### Changed

- Usage cost labels now explicitly describe an API list-price equivalent, not
  an Antigravity bill or account balance.
- Browser-visible product branding is now `NA2H`; the stable `hakimi` CLI and
  `hakimi_proxy` Python package identifiers are unchanged.
- Replaced misleading per-model quota rows with responsive, accessible shared
  window progress bars; model catalog quota data is now only a degraded
  availability fallback.

### Verified

- Passed 192 automated tests, Python compilation, lock validation, inline Web
  UI JavaScript parsing, interactive zh-CN/English and light/dark browser checks,
  and the 500-request fake-upstream Agent reliability gate with zero leaked
  credential leases.
- Built the 0.6.0 wheel and source distribution, checked the packaged verification
  CLI and Web asset, and excluded private configuration and runtime data.
- Operator-reported live Web full verification passed on 2026-08-30 with three
  inference requests in 9,871 ms after the tool-choice correction.

## [0.6.0] - 2026-08-28

### Added

- A short `hakimi serve --config ...` startup command that selects the config
  before importing the FastAPI application while preserving legacy entrypoints.
- A redacted `hakimi doctor` with text/JSON output for config, credential
  counts, proxy source, running version, and readiness. Default diagnosis uses
  local traffic only.
- An explicit `doctor --live` path that reuses the existing authenticated,
  staged credential health endpoint. A single account is selected
  automatically; multiple accounts require `--credential provider:id`.
- One state-driven first-use panel in the existing Web UI for browser login,
  credential repair, or generic OpenAI-compatible client configuration.
- `hakimi generate-key` for deliberate deployment-key rotation, plus automatic
  first-start provisioning that persists a missing key with mode 0600 and
  prints it only on the provisioning start.
- Session-only Web login by default, an explicit persistent-login choice, and
  logout that clears both browser stores.

### Security

- Doctor emits allowlisted summaries and never prints provider credentials,
  access/refresh tokens, proxy URLs, downstream Bearer values, or raw transport
  exceptions.
- The settings API returns only `auth_token_set`; it never returns or fills the
  deployment key into the settings DOM. Generic integration copying includes
  the authenticated key only after an explicit click and warns that the
  clipboard contains a secret.
- `hakimi serve` provisions authentication before starting any listener and
  fails closed if the generated key cannot be persisted. Bearer comparison
  uses a constant-time primitive; `/healthz` exposes only whether auth is enabled.

### Changed

- Quick Start now uses the uv-only `hakimi` entry and no longer requires a new
  user to hand-create YAML or OAuth fields before opening the Web UI.

### Verified

- Passed 163 automated tests, Python compilation, lock validation, Web UI
  JavaScript parsing, and the default 500-request Agent reliability gate.
- Built the 0.6.0 wheel and sdist with both legacy and `hakimi` console entries.
- Passed one authorized real `doctor --live` run across local, OAuth,
  Antigravity control-plane, and inference stages.

## [0.5.0] - 2026-08-28

### Added

- A public two-turn Agent compatibility scenario in the bounded reliability
  gate: raw fake Antigravity SSE emits a signed function call, the public
  Responses output is replayed with its tool result, and the second turn must
  finish with visible assistant text and no credential lease leak.
- A read-only GitHub Actions workflow with immutable checkout/setup-uv actions,
  locked uv dependencies, tests, compileall, the credential-free reliability
  gate, and package build verification.

### Changed

- Centralized creation of request-scoped upstream HTTP clients behind one app
  factory so acceptance can replace only the external transport while keeping
  all routing and protocol conversion real.

### Verified

- Proved stable function-call/result IDs and native thought-signature replay
  across two public streaming `/v1/responses` requests using no real credential
  or network traffic.

## [0.4.0] - 2026-08-27

### Added

- Public, traffic-free `/readyz` readiness: 200 with locally active capacity
  (including bounded busy capacity), and structured 503 when none is active.
- A bounded `python -m hakimi_proxy.reliability_gate` command that validates
  Responses routing, single-flight scheduling, lease cleanup, readiness, 429
  failover, upstream 503 classification, and transport timeout classification
  using only temporary fake upstreams.

### Verified

- Added public ASGI regressions for mid-stream client disconnect cleanup,
  upstream 503/timeout classification, cooldown readiness, and rotated OAuth
  refresh-token persistence across application restart.
- Passed the default 500-request reliability gate with all requests completed,
  one maximum in-flight upstream call, and zero leaked credential leases.
- Passed one authorized live `/v1/responses` smoke after OAuth refresh with
  `gemini-3.7-flash-tiered`, returning HTTP 200 and output `OK`.

### Removed

- Removed the EMP-specific model/provider panel from the Web UI. Standard
  `/v1/models`, `/v1/chat/completions`, and `/v1/responses` interfaces remain.

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
