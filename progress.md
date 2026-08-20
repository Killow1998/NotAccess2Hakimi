# Progress Log

## Session: 2026-08-19

### Phase 1: Baseline and credential boundary
- **Status:** complete
- **Started:** 2026-08-19
- Actions taken:
  - Confirmed Hakimi is clean and EMP contains unrelated local changes.
  - Recorded AGY suspension as a hard boundary.
  - Installed Python 3.12.13 and locked dependencies under `/tmp`.
  - Ran the full Hakimi unit suite.
- Files created/modified:
  - `task_plan.md`
  - `findings.md`
  - `progress.md`

## Test Results

| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| EMP unit suite (prior inspection) | Pass | 61 passed, 1 skipped | pass |
| Hakimi unit suite | Pass | 54 passed, 1 dependency deprecation warning | pass |
| AI Studio model discovery | Account lists `gemini-3.7-flash` | 37 models; target present | pass |
| AI Studio non-stream text | Exact marker returned | HTTP 200 with marker | pass |
| AI Studio streaming | Valid SSE JSON and marker | Invalid doubled `data:` prefix | fail |
| AI Studio non-stream text after fix | Exact marker returned | HTTP 200 with marker | pass |
| AI Studio streaming after fix, attempt 1 | Valid SSE | Upstream HTTP 503 after about 79 seconds | blocked by upstream |
| AI Studio tool call | `get_marker` call with marker | HTTP 200 with expected function call | pass |
| AI Studio 3.7 streaming after fix, attempt 2 | Valid SSE | Upstream HTTP 503 after about 35 seconds | blocked by upstream |
| AI Studio 3.6 streaming control | Valid SSE and marker | HTTP 200, valid SSE, marker present | pass |
| EMP to Hakimi with 3.7 | Responses converted through Hakimi | Chain reached Google; upstream HTTP 503 and credential cooldown | blocked by upstream |
| EMP to Hakimi with 3.6 control | Responses converted through Hakimi | HTTP 200 with `EMP_HAKIMI_OK` | pass |

## Error Log

| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 2026-08-19 | Hakimi runtime unavailable | 1 | Installed Python and dependencies under `/tmp` through the configured proxy |
| 2026-08-19 | Streaming emitted `data: data: {...}` | 1 | Root cause identified at adapter/route SSE framing boundary; fix pending |
| 2026-08-19 | TestClient streaming regression harness hung | 1 | Removed the heavy harness; use the existing adapter contract tests plus the original real request |
| 2026-08-19 | `uv lock` network blocked in sandbox | 1 | Re-run through the configured proxy outside the network sandbox |
| 2026-08-19 | Post-fix real stream returned upstream 503 | 1 | Split acceptance cases and retry only the blocked stream after cooldown |
| 2026-08-19 | Second post-fix 3.7 stream returned upstream 503 | 2 | Stop repeating 3.7; use 3.6 as a control to isolate model availability from framing code |
| 2026-08-19 | EMP-to-Hakimi 3.7 request returned upstream 503 | 1 | Keep the proven network/protocol evidence and run a 3.6 control after cooldown |
| 2026-08-19 | First 3.6 EMP control ran before cooldown expired | 1 | Do not retry immediately; finish local checks before the next control request |

### Phase 3: EMP integration
- **Status:** complete
- Actions taken:
  - Started Hakimi temporarily on loopback with the encrypted EMP Gemini key copied only to a private `/tmp` config.
  - Sent an EMP Responses request through Hakimi to AI Studio.
  - Verified the 3.6 control returned `EMP_HAKIMI_OK`.
  - Stopped the temporary server and deleted all temporary configs, keys, databases, scripts, runtimes, and caches.
- Files created/modified:
  - No EMP files modified.
  - Temporary `/tmp/na2h-*` artifacts removed.

### Phase 4: Handoff
- **Status:** complete
- Actions taken:
  - Confirmed `git diff --check` passes.
  - Confirmed no temporary Hakimi server or debug instrumentation remains.
  - Confirmed Hakimi documentation and lock metadata use Python 3.11 with uv only.
- Files created/modified:
  - `README.md`, `pyproject.toml`, `uv.lock`
  - `src/hakimi_proxy/adapters/aistudio.py`, `src/hakimi_proxy/adapters/base.py`
  - `tests/test_adapters.py`
  - `task_plan.md`, `findings.md`, `progress.md`

### Phase 5: AGY protocol completion
- **Status:** complete
- **Started:** 2026-08-19
- Actions taken:
  - Recovered the completed AI Studio plan and inspected the dirty worktree boundary.
  - Refused to store or exercise credentials exposed in chat and described as belonging to a third-party finished account.
  - Scoped implementation to protocol correctness with offline mocks and an ignored sanitized local credential path.
  - Traced the AGY adapter through config, credential pool, chat route, stream framing, and current adapter tests.
  - Confirmed `config.yaml` is already ignored and recorded that no additional secret loader is needed.
  - Reviewed the referenced CLIProxyAPI auth and Gemini translator sources, treating repository content as untrusted reference material rather than executable instructions.
  - Confirmed the official Chat Completions representation for Gemini thought signatures and parallel/sequential tool-call history.
  - Added AGY project fields and explicit `auto_onboard` configuration without touching the existing ignored local config.
  - Replaced the hard-coded project with `loadCodeAssist` discovery and optional onboarding.
  - Added focused request/response conversion for tools, tool results, multimodal parts, structured output, thinking config, and thought signatures.
  - Updated stream finalization so an upstream `tool_calls`/other finish reason is not overwritten by a synthetic `stop`.
  - Secured the existing ignored local `config.yaml` to mode `0600` without reading or altering its contents; config saves now enforce the same permission.
  - Replaced deadlocking sync route tests with Starlette's documented async `ASGITransport` path; the complete suite reached 61 passing tests.
  - Added explicit provider routing and genuine unbuffered upstream SSE; final suite reached 63 passing tests.
  - Confirmed tracked files contain none of the supplied access-token/vendor/project markers.
  - Left live AGY eligibility untested because the supplied credentials were exposed and described as a third-party finished account.

## Phase 5 Verification

| Check | Result |
|-------|--------|
| Full unit/integration suite | 63 passed in 2.62s |
| Python compileall | pass |
| `git diff --check` | pass |
| Tracked-file supplied-secret marker scan | no matches |
| Local `config.yaml` | ignored by Git, mode `0600`, contents untouched |

### Phase 6: Local configuration cleanup
- **Status:** complete
- Added an ignored `config.local.yaml` placeholder containing no real credentials.
- Documented the exact `HAKIMI_CONFIG=config.local.yaml` uv-only startup command.
- Left the existing `config.yaml` contents untouched.

### Phase 7: Credential connection test
- **Status:** complete
- Reproduced the missing test surface by inspecting the Web UI controls and registered API routes.
- Confirmed `ACTIVE` currently means locally schedulable, not remotely verified.
- Chosen fix: a credential-specific admin test endpoint plus Test buttons for both provider tabs.
- The planning session-catchup helper remains unavailable at its installed-skill path; continued from the already current plan, findings, progress, status, and diff instead of retrying it.
- Added failing API/UI regression checks, observed the expected 404/missing-button failures, then implemented the endpoint and buttons; focused checks now pass.
- Full verification reached 64 passing tests; Python compilation, inline JavaScript parsing, and `git diff --check` all pass.
- Files modified for this phase: `src/hakimi_proxy/routes/admin.py`, `src/hakimi_proxy/web/index.html`, `tests/test_admin.py`, and the planning records.

### Phase 8: Test timeout diagnosis
- **Status:** complete
- Correlated the log timestamps with the adapter's 30-second OAuth refresh timeout.
- Confirmed the active local config has no explicit upstream proxy.
- User requested comparison with the prior EMP/Hakimi session; began recovering the exact runtime and proxy evidence instead of treating the current sandbox curl result as authoritative.
- `jq` is not installed and `rtk` cannot dispatch it; switched to the existing uv Python runtime for structured JSONL inspection.
- Located the root prior-session rollout at `/home/nuc/.codex/sessions/2026/08/17/rollout-2026-08-17T05-08-48-01a00f9f-d50b-7662-84d2-89013c25e901.jsonl`.
- Narrowed the historical evidence to the actual command-execution records around the successful EMP/Hakimi markers, avoiding broad transcript output that could contain credentials.
- Initial event-index matching selected duplicated UI completion events rather than tool results; changed to exact `call_id` matching before reading historical outputs.
- Historical tool outputs use mixed string/content-block shapes; the first string-only parser failed, so extraction was changed to flatten both shapes with secret-pattern redaction.
- Recovered the exact historical network setup: external tests used the local proxy on port 7897, while the current `config.local.yaml` has an empty proxy.
- The sandbox blocked `ss` netlink inspection, so connectivity was verified instead with an approved credential-free OAuth HEAD request through 7897; it succeeded in 0.62 seconds.
- Added a regression for blank timeout messages, observed the expected failure, then included the exception class name; the focused connection tests now pass.
- Updated the ignored local config to use `http://127.0.0.1:7897`; the running Uvicorn process must restart to load it.
- Final verification: 65 tests passed; Python compilation and `git diff --check` passed; `config.local.yaml` remains mode `0600`.

### Phase 9: EMP-style single-page credential UX
- **Status:** specification complete; implementation started in Phase 10
- Preserved the existing dirty worktree and confirmed EMP's UI is also a self-contained `web/index.html` suitable as a direct interaction reference.
- Root cause found: Hakimi masks secrets in list responses, renders empty Edit fields, then replaces the stored credential with those submitted values.
- Read EMP's complete current Web UI and grounded the redesign scope with Goudi: keep the single-page target, but first prove safe partial credential edits before replacing the visual shell.
- Confirmed EMP's backend explicitly preserves omitted secrets and exposes only secret-set metadata; recorded this as the behavior to reproduce without importing EMP's separate encrypted-store architecture.
- Compared EMP's merge/public-config tests with NA2H's current admin routes and identified the safer target: endpoint-specific PATCH-like PUT semantics rather than EMP's whole-config masked-sentinel round trip.
- Added `UX_REDESIGN_PLAN.md` with the EMP/NA2H comparison, target wireframe, API contracts, interaction flows, file-level patch map, staged commits, automated/manual test matrices, acceptance criteria, cut list, rollback boundary, and LunaMax execution constraints.
- Plan verification: 692 lines before the final clarification pass, all 15 major sections present, no real credential markers found, and `git diff --check` passes.

### Phase 10: UX redesign implementation
- **Status:** in progress
- Started with the highest-risk contract: partial credential updates must preserve omitted or blank secrets.
- Added partial AI Studio and Antigravity update models. Omitted/blank secrets now preserve stored values; changing OAuth identity clears cached access token, expiry, and stale project discovery state.
- Credential listing now exposes only `*_set` metadata and full non-secret Antigravity client ID; no secret fragments are returned.
- TDD slice is green: `tests/test_admin.py` has 15 passing tests.
- Replaced the sidebar/page/tab shell with one responsive page containing health/stats, both credential providers, usage, and collapsed settings.
- Edit forms now prefill safe fields, keep secret inputs blank, and send only newly entered secrets; Test has per-credential busy state and inline success/error results.
- Added `latency_ms` to credential-test responses and documented the new partial-update/list-redaction contract in `README.md`.
- Added trust-boundary validation rejecting blank required secrets on credential creation.
- Automated verification is green: 69 tests, Python compileall, inline JavaScript parse, and `git diff --check`. Manual desktop/mobile browser acceptance remains pending.

### Phase 11: EMP-compatible proxy auto-detection
- **Status:** in progress
- Confirmed EMP checks explicit proxy environment, system proxy discovery, and Linux GNOME manual proxy settings; NA2H currently only passes configured `proxy` or relies on httpx environment handling.
- Current implementation target: explicit config wins; otherwise apply detected proxy to standard environment variables so existing adapters inherit it, with a non-secret source label for health/UI diagnostics.
- Added `hakimi_proxy.proxy.configure_proxy_environment()` with EMP's environment → system → GNOME → direct order and safe URL validation.
- Startup and settings updates now preserve explicit `config.proxy` precedence; `/healthz`, `/api/config`, and the Settings panel expose only the source label.
- Updated README/config example to document automatic detection. Full verification: 74 tests, compileall, inline JavaScript parse, and `git diff --check` pass.
- Inspected local AGY credential metadata without printing values. `config.local.yaml` had a malformed `client_secret` with appended token metadata; repaired it in place, preserved the standalone secret and refresh token, and kept the file mode `0600`/Git ignore boundary. No live OAuth request was made.

### Phase 12: AGY endpoint fallback
- **Status:** complete
- User logs showed OAuth refresh 200 and `loadCodeAssist` 200, followed by daily `generateContent` HTTP 404.
- Root cause: the adapter returned any HTTP response immediately, so its documented daily → production fallback only handled transport exceptions.
- Added 404 fallback with an offline regression test; full verification now passes with 75 tests, compileall, inline JavaScript parse, and `git diff --check`.

### Phase 13: CPA 429 diagnosis
- **Status:** complete
- Official CLIProxyAPI reports show the same Antigravity pattern: token/model discovery succeeds while generation returns `429 RESOURCE_EXHAUSTED`; no confirmed maintainer fix is linked.
- Kept the existing daily → production fallback. Added safe Test error classification for upstream status, provider reason, `Retry-After`, and known quota reset metadata without returning raw bodies.
- Full verification: 76 tests passed; Python compileall and `git diff --check` passed.
- Current blocker is upstream/account-side throttling, not OAuth refresh or local endpoint selection. Do not add aggressive retries or quota-evasion rotation.

### Phase 14: AGY model catalog verification
- **Status:** complete
- A single metadata-only `fetchAvailableModels` probe with `HAKIMI_CONFIG=config.local.yaml` returned 200 from daily; no generation request was made.
- The live catalog contains `gemini-3.6-flash-high`, `gemini-3.6-flash-medium`, `gemini-3.6-flash-low`, `gemini-3.6-flash-tiered`, and `gemini-3.7-flash-tiered`; it does not contain `gemini-3.7-flash-high`.
- Added the catalog-confirmed tier IDs to the AGY model set and resolve the old `gemini-3.7-flash` display alias to `gemini-3.7-flash-tiered`. Deliberately did not add the unverified `3.7-high -> 3.6-high` downgrade.
- Updated the credential Test model and README examples to use `gemini-3.7-flash-tiered`. Full verification: 77 tests passed; compileall and `git diff --check` passed.

### Phase 15: Responses API compatibility
- **Status:** complete
- User requested a real Responses API test path before wiring Hakimi into EMP.
- Added an additive `/v1/responses` facade over the shared Chat Completions retry/metering path.
- Added request conversion for instructions, text/image input, tool history, tool definitions, tool choice, reasoning, and JSON output format.
- Added non-streaming Responses conversion for text, function calls, usage, and model identity.
- Added Responses SSE conversion for text deltas, function-call argument deltas, completion events, and usage.
- Verification so far: 9 Responses tests and the existing related adapter/route tests pass.

### Phase 16: EMP provider handoff
- **Status:** complete
- Inspected EMP's provider schema and routing contract without modifying its dirty worktree.
- Handoff uses `protocol=responses`, `auth_mode=api_key`, Base URL `http://127.0.0.1:8000/v1`, and an explicit `antigravity/` model upstream ID when AGY routing must be deterministic.
- Live dual-process generation was not run by Codex in this phase; the final response includes the user-run curl and Codex acceptance commands.

### Phase 17: Public UI root auth normalization
- **Status:** complete
- Reproduced the screenshot's `401 Invalid or missing bearer token` at `/` with a regression test while bearer auth was enabled.
- Root cause was `rstrip("/")` converting `/` to `""`, so the UI allowlist entry `/` never matched.
- Fixed path normalization in `BearerAuthMiddleware` and confirmed the login markup is reachable without a bearer header.
- Verification: targeted regression passed, full NA2H suite passed (87 tests), Python compilation, Web UI JavaScript parse, and `git diff --check` passed.

### Phase 18: Live Responses acceptance
- **Status:** in progress
- The credential Test action reached OAuth refresh `200` and Antigravity `generateContent 200` for `my-antigravity`.
- A real `/v1/responses` non-stream request with `max_output_tokens=512` returned `output_text: "OK"` and a completed message for `antigravity/gemini-3.7-flash-tiered`.
- A real `/v1/responses` SSE request returned `response.output_text.delta`, `response.output_text.done`, and `response.completed` with `output_text: "OK"`.
- Updated the ignored local EMP `config.json` model entry to `context_window: 1048576` and `reasoning_levels: ["low", "medium", "high"]`; the file remains mode `0600` and Git-ignored.
- EMP now routes `hakimi/gemini-3.7-flash-tiered` through the local Hakimi Responses Provider. Codex switched to both `high` and `medium`, produced normal responses, and displayed `996K window` / `63K used`.
- Phase acceptance complete: Codex → EMP → Hakimi Responses → Antigravity → Gemini 3.7 Flash.

### Phase 19: Codex tool-call compatibility
- **Status:** in progress
- Reproduced the user-visible symptom: Codex turns complete with no `final_agent_item`, while EMP, NA2H, and Antigravity all return HTTP 200.
- Ran the local Codex 0.147.0 compatibility fixture; Codex accepted the same Responses stream, ruling out generic EMP/Responses streaming failure.
- Captured a real Codex request shape using a temporary local fake provider. Tools are nested under `input[0].type=additional_tools`, with a `functions` namespace and a `custom` `exec` tool; top-level `tools` is null.
- Root cause is isolated to `src/hakimi_proxy/routes/responses.py::_tools()`, which ignores `additional_tools` and custom tools. No EMP files were changed.
- Next: write the failing translator regression, implement the narrow NA2H normalization, then rerun NA2H and Codex compatibility tests.

### Phase 19 completion
- Added failing tests for Codex `additional_tools`, custom tool history, non-stream custom output, and streaming custom output; the pre-fix run failed 4 tests as expected.
- Implemented the narrow fix in `src/hakimi_proxy/routes/responses.py`:
  - recursively flattens `additional_tools` namespaces;
  - maps `custom` tools to a JSON `input` parameter for the existing Chat tool bridge;
  - converts `custom_tool_call`/`custom_tool_call_output` history;
  - emits `response.custom_tool_call_input.delta` and `custom_tool_call` output items;
  - keeps regular function-call behavior intact.
- Verification: focused Responses tests 13 passed; full NA2H suite 91 passed; Python compileall and `git diff --check` passed.
- EMP was not modified; no debug instrumentation or temporary probe remains.

### Phase 20: AGY thought-signature round-trip
- **Status:** complete
- Started from the user’s restarted Codex logs showing AGY `streamGenerateContent` 400 responses after an initial 200 tool turn.
- Reproduced the exact failure against an isolated uv NA2H instance and captured the safe upstream reason: `Function call is missing a thought_signature in functionCall parts`.
- Added failing regression assertions for signature preservation in regular/custom Responses history and regular/custom streamed output, then implemented the narrow round-trip fix in `src/hakimi_proxy/routes/responses.py`.
- Verified with real local-runtime traffic without printing credential values: non-streaming custom-tool two-turn loop returned 200/200; streaming custom-tool two-turn loop returned 200/200, with the first output carrying a signature and the second completing as a message.
- EMP stayed running and unmodified. The isolated NA2H process was stopped after testing.
- Removed the tracked legacy environment-manager file; the hidden-file scan is clean. All commands for this phase used `uv`.

## Phase 20 Verification

| Check | Result |
|---|---|
| Responses-focused tests | 13 passed |
| Full NA2H suite | 91 passed |
| Python compileall | pass |
| `git diff --check` | pass |
| Hidden legacy-config scan | clean |
| Live non-streaming AGY tool round-trip | HTTP 200 first turn / HTTP 200 second turn |
| Live streaming AGY tool round-trip | HTTP 200 first turn / HTTP 200 second turn |

### Phase 21: CPA-aligned tool history pairing
- **Status:** complete
- Read the public CLIProxyAPI Responses translator under `/tmp/cliproxyapi-ref` and kept only the relevant pairing behavior; no CPA source was copied into NA2H.
- Added standard Responses reasoning carriers for detached thought signatures and retained multiple carriers through non-streaming and streaming conversion.
- Added stable IDs to Gemini `functionCall` and `functionResponse` parts. This fixed the remaining second-turn AGY `400` that appeared after the thought-signature fix.
- Verification: 44 focused adapter/Responses tests, 97 full NA2H tests, Python compileall, and `git diff --check` passed.
- Real low-reasoning acceptance: non-streaming tool loop `200 -> 200`; streaming tool loop `200 -> 200`; both second turns completed with message output.

### Phase 22: Antigravity OAuth UX and refresh lifecycle
- **Status:** complete
- Verified the official Antigravity CLI repository boundary: public install/auth docs and changelog, but no agent source implementation to copy.
- Added `src/hakimi_proxy/oauth.py` with a local state-validated browser callback flow and automatic credential creation from the authorized Google account.
- Added per-account refresh locking, rotated refresh-token persistence, and actionable `invalid_grant` handling. No periodic keepalive loop or fingerprint spoofing was added.
- Added account metadata and browser-login controls to the single-page UI; manual OAuth fields remain only as a fallback.
- Verification: 100 tests passed, Python compileall passed, Web UI script parse passed, `git diff --check` passed, and the real local callback state flow passed without contacting Google.

### Phase 23: Remote OAuth and streaming failover
- **Status:** complete
- Existing tool-call compatibility is already covered by the CPA-aligned history/signature fixes; do not duplicate that work.
- Current OAuth only accepts the loopback HTTP callback, so a browser on another computer cannot complete a server-hosted NA2H login without copying the callback result.
- Current chat streaming emits a synthetic downstream chunk before consuming the first upstream event, so a post-200 upstream failure cannot be retried invisibly.
- Added `POST /api/credentials/antigravity/oauth/complete` for a copied localhost callback URL or one-time OAuth code; state and duplicate-code checks remain server-side.
- Updated the single-page UI with copy/open/paste OAuth controls while keeping local automatic callback polling.
- Added a first-event gate for streamed upstream responses, pre-first-event credential failover, and normalized post-first-event SSE errors through both Chat Completions and Responses.
- Verification: 106 tests passed, Python compileall passed, Web UI script parse passed, `git diff --check` passed, and the uv-only legacy-config scan stayed clean.

## Final Verification

- NA2H full suite: 117 passed.
- Adapter/Responses focused suite: covered by the full suite; prior focused suite was 44 passed.
- NA2H Python compile, Web UI JavaScript parse, and raw `git diff --check`: passed.
- Phase 24 checks: concurrency, failover, terminal error, invalid JSON, empty output, stream cleanup, admin status, and `/healthz` in-flight count: passed.
- EMP full suite: 75 tests, 1 intentionally skipped real Codex CLI demo, passed with loopback permission escalation; the first sandbox run had 7 socket-permission errors and was classified as environment-only.

## Phase 5 Error Log

| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 2026-08-19 | Planning skill session-catchup helper path was unavailable | 1 | Recovered from existing planning files plus Git status/diff |
| 2026-08-19 | `uv run` could not create its cache lock in the read-only home cache | 1 | Use `/tmp/na2h-uv-cache` for verification |
| 2026-08-19 | Focused test command could not spawn `pytest` | 1 | The temporary uv environment lacked the dev extra; sync locked dev dependencies |
| 2026-08-19 | Full suite hung after the 20 adapter tests at the first `TestClient` request | 1 | Confirmed Starlette 1.6 requires `httpx2`; add it to the dev extra and rerun |
| 2026-08-19 | The same `TestClient` request hung after installing `httpx2` | 2 | Faulthandler isolated the blocking portal deadlock; convert route tests to async `ASGITransport` per Starlette docs |
| 2026-08-19 | First unbuffered-stream test failed because the mock response used eager `content=` | 1 | Use a custom one-chunk `AsyncByteStream` so the fixture models a live upstream |
## Phase 24 start (2026-08-20)

- Restored the existing dirty checkout and confirmed the baseline suite: 106 tests passed.
- Locked the implementation scope to the single-operator reliability contract: one in-flight request per credential, 30-second bounded acquisition wait, no quota dashboard, Virtual Key, or multi-process coordination.
- No live Google credential or EMP worktree will be used for verification; tests remain mock-driven.
- Completed Phase 24 in the shared NA2H checkout: credential leases, unified failure classification, stream/non-stream cleanup, empty-output rejection, runtime status, bounded-capacity errors, and the existing UI feedback.
- Final verification: `UV_CACHE_DIR=/tmp/na2h-uv-cache uv run pytest -q` -> 117 passed; Python compileall, Web UI `new Function` parse, `git diff --check`, and uv-only/credential-pattern scans completed. EMP was not touched.

## Phase 25: Responses custom-tool ID compatibility (2026-08-20)

- **Status:** complete
- Normalized non-streaming and streaming `custom_tool_call` item IDs to the
  OpenAI Responses `ctc_*` format while preserving the upstream `call_id`.
- Kept regular `function_call` IDs unchanged and documented the need for a
  fresh Codex session when switching provider families with old tool history.
- Verification: Responses tests 19 passed; full suite 118 passed.
