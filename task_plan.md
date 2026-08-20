# Task Plan: Hakimi provider acceptance

## Goal
Keep the verified AI Studio path intact and complete the AGY adapter protocol for accounts the operator owns and is authorized to use, without storing or exercising exposed third-party credentials.

## Current Phase
Phase 24 complete (Reliability contract: single-flight leases, error taxonomy, and stream cleanup)

## Phases

### Phase 1: Baseline and credential boundary
- [x] Confirm current code/test/runtime state
- [x] Reuse the existing encrypted EMP AI Studio credential without printing it
- **Status:** complete

### Phase 2: Hakimi verification and minimal fixes
- [x] Run Hakimi tests in an isolated environment
- [x] Validate model discovery, text, streaming, and tool calling against AI Studio
- [x] Fix only failures required for those acceptance paths
- **Status:** complete

### Phase 3: EMP integration
- [x] Point a temporary EMP configuration at Hakimi
- [x] Validate the EMP-to-Hakimi request path
- **Status:** complete

### Phase 4: Handoff
- [x] Re-run focused/full checks and inspect diffs
- [x] Report AGY appeal blocker and remaining manual action
- **Status:** complete

### Phase 5: AGY protocol completion
- [x] Preserve the existing dirty worktree and inspect all adapter consumers
- [x] Add dynamic project discovery/onboarding behavior with mocked HTTP tests
- [x] Cover the minimum message, tool, multimodal, thought-signature, and streaming mappings required by the current OpenAI facade
- [x] Add an ignored local credential path and sanitized example only; never write supplied secrets
- [x] Run focused/full tests and inspect the final diff
- **Status:** complete

### Phase 6: Local configuration cleanup
- [x] Keep the existing private `config.yaml` untouched
- [x] Add an ignored `config.local.yaml` placeholder for authorized credentials
- [x] Document the exact uv-only startup command
- [x] Verify ignore rules, file permissions, tests, and diff hygiene
- **Status:** complete

### Phase 7: Credential connection test
- [x] Confirm the UI and admin API have no credential-specific test action
- [x] Add a credential-specific test endpoint with mocked regression coverage
- [x] Add Test buttons and clear success/failure feedback in the Web UI
- [x] Run focused and full verification
- **Status:** complete

### Phase 8: Test timeout diagnosis
- [x] Classify the blank 502 using timestamps and the OAuth refresh boundary
- [x] Expose timeout/error types in the Test result
- [x] Verify OAuth refresh uses the configured proxy path
- [x] Run regression and full verification
- **Status:** complete

### Phase 9: EMP-style single-page credential UX specification
- [x] Identify why Edit shows empty secret fields and can overwrite credentials
- [x] Inspect EMP's current UI and backend secret-preservation patterns
- [x] Compare EMP and NA2H interaction/user-friendliness in detail
- [x] Write an implementation-ready, file-level redesign plan for LunaMax
- **Status:** complete

### Phase 10: Implement the UX redesign
- [x] Make credential edits preserve omitted secrets
- [x] Replace the paged shell with one responsive page
- [x] Add per-credential busy and inline Test results
- [x] Run automated acceptance checks
- [ ] Run manual desktop/mobile browser acceptance checks
- **Status:** in progress (implementation and automated checks complete; manual browser pass pending)

### Phase 11: Match EMP proxy auto-detection
- [x] Detect explicit environment/system/GNOME proxies when `config.proxy` is empty
- [x] Preserve explicit config proxy precedence
- [x] Surface the selected proxy source without exposing credentials
- [x] Add mocked regression coverage and rerun full verification
- **Status:** complete

### Phase 12: Fix AGY HTTP endpoint fallback
- [x] Reproduce daily endpoint 404 with an offline mock
- [x] Fall back to the production endpoint on HTTP 404
- [x] Run full regression and protocol checks
- **Status:** complete

### Phase 13: Diagnose upstream AGY rate limits
- [x] Compare the daily/prod 404→429 pattern with official CLIProxyAPI reports
- [x] Preserve safe upstream status, reason, and retry/reset metadata in credential Test responses
- [x] Add a regression for `RESOURCE_EXHAUSTED` 429 responses
- [x] Run the full regression suite and static checks
- **Status:** complete; upstream account/server throttling remains external to NA2H

### Phase 14: Verify current AGY model IDs
- [x] Query `fetchAvailableModels` once with the local runtime credential, without generation
- [x] Confirm the account's catalog contains `gemini-3.6-flash-*` tiers and `gemini-3.7-flash-tiered`
- [x] Reject the unverified `gemini-3.7-flash-high` alias instead of silently downgrading it
- [x] Route the existing `gemini-3.7-flash` display alias to the catalog-confirmed tiered ID
- [x] Add regression coverage and rerun the full suite
- **Status:** complete

### Phase 15: Add Responses API compatibility
- [x] Define the smallest public `/v1/responses` contract needed by Codex
- [x] Add one non-streaming text tracer test and implementation
- [x] Add streaming text and tool-call regression tests and implementation
- [x] Preserve the existing `/v1/chat/completions` path and usage metering
- [x] Run focused/full verification and inspect the diff
- **Status:** complete

### Phase 16: EMP provider handoff
- [x] Inspect EMP's current provider/config contract without modifying its dirty worktree
- [x] Write the exact local provider configuration and startup/test sequence
- [x] Identify any EMP-side protocol limitation or required bridge setting
- **Status:** complete; live dual-process acceptance remains user-run

### Phase 17: Fix public UI root auth normalization
- [x] Reproduce the browser's root-page 401 with an authenticated ASGI route test
- [x] Normalize `/` before checking the public UI path allowlist
- [x] Run the focused regression and full verification suite
- **Status:** complete

### Phase 18: Live Responses acceptance
- [x] Confirm a real Antigravity credential test reaches OAuth and `generateContent`
- [x] Confirm a real non-streaming `/v1/responses` request returns visible `output_text`
- [x] Confirm live Responses SSE output
- [x] Set the local EMP model metadata to the verified 3.7 Flash limits and reasoning levels
- [x] Add Hakimi as an EMP Responses Provider and test the imported model in Codex
- **Status:** complete; end-to-end Codex acceptance passed

### Phase 19: Codex tool-call compatibility
- [x] Add a regression fixture for Codex `additional_tools` input
- [x] Preserve function and custom tool declarations when translating Responses to Chat
- [x] Emit/accept the Responses events required for Codex custom tool execution
- [x] Run focused/full tests and the local Codex compatibility check
- **Status:** complete

### Phase 20: AGY thought-signature round-trip
- [x] Reproduce the post-tool-loop 400 and capture the upstream error body
- [x] Add a regression for preserving signatures through Responses history
- [x] Preserve signatures in non-streaming and streaming function/custom tool output
- [x] Validate one real non-streaming and one real streaming tool round-trip
- [x] Remove the tracked legacy environment-manager configuration and verify uv-only references
- [x] Run focused/full tests and static checks
- **Status:** complete

### Phase 21: CPA-aligned tool history pairing
- [x] Pull the public CLIProxyAPI reference into `/tmp/cliproxyapi-ref` without adding it to the project
- [x] Compare its Responses carrier and function-call/function-response ID handling with NA2H
- [x] Preserve detached reasoning carriers in non-streaming and streaming Responses conversion
- [x] Include stable IDs on Gemini `functionCall` and `functionResponse` parts
- [x] Validate real low-reasoning non-streaming and streaming two-turn tool loops
- [x] Run focused/full tests and diff hygiene checks
- **Status:** complete

### Phase 22: Antigravity OAuth UX and refresh lifecycle
- [x] Confirm the official CLI repository publishes documentation/changelog, not its agent implementation
- [x] Keep request headers/protocol aligned with observed official behavior without adding fingerprint spoofing
- [x] Add per-account refresh locking, refresh-token rotation persistence, and actionable invalid-grant errors
- [x] Add a local browser OAuth callback flow with state validation and short-lived sessions
- [x] Auto-create a local Antigravity credential from the authorized account email
- [x] Add UI controls, API coverage, documentation, and uv verification
- **Status:** complete

### Phase 23: Remote OAuth and streaming failover
- [x] Add a one-time remote OAuth completion endpoint accepting a callback URL or code
- [x] Update the Web UI to copy the authorization URL and paste the authorization result
- [x] Add regression coverage for state validation, one-time code consumption, and remote credential creation
- [x] Buffer the first upstream stream event before emitting downstream success frames
- [x] Retry a stream on pre-first-event upstream failure, and normalize post-first-event failures
- [x] Run focused/full tests, Web UI syntax checks, and diff hygiene checks
- **Status:** complete

### Phase 24: Reliability contract
- [x] Add single-flight per-credential leases with a 30-second bounded wait
- [x] Classify upstream/OAuth failures once and apply retry, cooldown, disable, or fail-fast actions
- [x] Release leases across non-streaming, streaming, cancellation, and Credential Test paths
- [x] Reject silent empty completions and preserve Responses stream error semantics
- [x] Expose safe runtime health/in-flight/last-error fields in the existing admin UI
- [x] Add concurrency, failover, error, stream-cleanup, and status regression coverage
- [x] Run full uv verification, diff hygiene, and secret-scan checks without touching EMP
- **Status:** complete

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Freeze AGY requests and code | The account has a product-level Terms of Service suspension; do not retry or evade it |
| Use temporary runtime/config paths | Keep secrets and generated data out of Git |
| Preserve EMP dirty worktree | It contains unrelated user work |
| Reject supplied account credentials | They were exposed in chat and described as a third-party finished account; implementation and tests must use mocks only |
| Keep a separate local placeholder | It organizes future authorized credentials without reading or overwriting the existing private `config.yaml` |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| Hakimi Python/dependency environment unavailable in prior inspection | 1 | Reuse installed Python where possible or build an isolated `/tmp` environment |
| Real AI Studio stream emitted `data: data: {...}` | 1 | Fix the shared adapter/route SSE contract and add a regression test |
| `uv lock` could not reach PyPI inside the sandbox | 1 | Re-run through the configured local proxy with network approval |
| Planning session catchup helper not found | 1 | Recover from existing plan files plus Git status/diff instead |
| `uv run` could not create a cache lock under the read-only home cache | 1 | Re-run with task-specific `UV_CACHE_DIR` under `/tmp` |
| Focused test command could not find `pytest` | 1 | Sync the existing locked dev extra into the temporary uv environment |
| Full suite hung on the first Starlette `TestClient` request | 2 | `httpx2` alone still deadlocks in the blocking portal; switch route tests to the documented async `ASGITransport` path |
| Streaming assertion saw an already-consumed mock response | 1 | Replace the eager `content=` fixture with a real `AsyncByteStream` |
| `node --check <(sed ...)` could not open the process-substitution path | 1 | Parse the inline script with Node's in-memory `new Function` check instead |
| EMP server tests could not create loopback sockets in the managed sandbox | 1 | Re-run the unchanged EMP suite with controlled loopback permission; 75 tests passed, 1 skipped |
| Temporary custom-tool probe had a mismatched list/parenthesis close | 1 | Corrected the throwaway probe before rerunning; no repository code was involved |
| AGY returned 400 after a successful tool call | 1 | Captured `Function call is missing a thought_signature`; preserve the signature on the Responses tool item and replay it on the next Chat/Gemini request |
| OAuth manager unit test could not bind a loopback socket in the managed sandbox | 1 | Keep socket-free state-machine coverage in the repository; reserve the real callback listener check for an approved runtime smoke test |
