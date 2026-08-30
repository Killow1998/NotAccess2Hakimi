# Task Plan: Hakimi provider acceptance

## Goal
Make NA2H a reliable, provider-neutral, single-node Gemini gateway while
preserving its verified AI Studio and authorized Antigravity paths, public
OpenAI-compatible contracts, and strict credential boundary.

## Current Phase
Phase 52 complete; reviewed full-verification and localized Web candidate

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
- [x] Run manual desktop/mobile browser acceptance checks
- **Status:** complete; later operator acceptance also covered OAuth, health, and integration states

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

### Phase 25: Responses custom-tool ID compatibility
- [x] Normalize custom-tool item IDs for streaming and non-streaming Responses
- [x] Preserve tool-result pairing IDs and regular function-call behavior
- [x] Run focused/full tests and push v0.1.1
- **Status:** complete

### Phase 26: Rich model catalog and EMP discovery
- [x] Centralize advertised model IDs and capability metadata in one module
- [x] Make both adapters and `/v1/models` consume the shared catalog
- [x] Advertise context, output, reasoning, modalities, tools, streaming, and provenance without fabricating unknown values
- [x] Add regression coverage for EMP's generic discovery contract
- **Status:** complete

### Phase 27: Stable startup and bounded diagnostics
- [x] Stop forcing hot reload in normal `python -m` startup
- [x] Add an explicit uv-only development reload command
- [x] Add a private, redacted, size-bounded diagnostic log and expose only its safe status/path
- [x] Keep application version and package version aligned
- **Status:** complete

### Phase 28: Model and EMP integration Web UI
- [x] Show advertised models and capability summaries in the existing single page
- [x] Show copyable EMP Provider settings without exposing the bearer token
- [x] Keep operation feedback inline and preserve the zero-build frontend
- **Status:** complete

### Phase 29: Cross-repository verification and handoff
- [x] Run focused/full NA2H tests, compile, Web UI parse, diff and secret scans
- [x] Verify EMP parses a representative NA2H model with context/reasoning/modalities
- [x] Update version, changelog, README, findings, and progress
- [x] Leave live AGY generation for the operator's final test
- **Status:** complete

### Phase 30: Codex unsigned tool-history replay
- [x] Isolate the first failing turn from the reported Codex rollout
- [x] Reproduce streamed upstream 400 bodies being masked as local 500s
- [x] Align missing-signature replay with CPA's first-function-call marker rule
- [x] Cover the exact Responses custom-tool conversion path and parallel calls
- [x] Run focused/full uv verification and publish patch release metadata
- **Status:** complete

### Phase 31: Server-safe remote OAuth
- [x] Add explicit local/remote OAuth start modes
- [x] Make remote mode generate a valid session without binding callback port 51121
- [x] Preserve local automatic callback behavior and state/code validation
- [x] Keep one login action and select local/remote completion from the current browser host
- [x] Add socket-free remote-mode regressions and run focused verification
- **Status:** complete

### Phase 32: Portable credential backup and restore
- [x] Define a versioned credentials-only bundle that excludes access tokens, proxy, bearer auth, and usage data
- [x] Add export with no-store/download headers and local-or-HTTPS transport enforcement
- [x] Add import preview plus explicit skip/overwrite conflict handling
- [x] Add Web UI download/upload confirmation without displaying stored secrets
- [x] Preserve mode-0600 config persistence and add round-trip/security regressions
- **Status:** complete

### Phase 33: Layered Antigravity health checks
- [x] Separate passive runtime health from active OAuth/control-plane/inference checks
- [x] Reuse existing credential leases and safe upstream error classification
- [x] Avoid background polling and any automatic generation traffic
- [x] Show actionable health stages and last-check state in the existing credential card
- [x] Verify staged behavior with mocked regressions and full automated checks
- [x] Pass one post-restart operator live check across all four stages
- **Status:** complete

### Phase 34: Reliability contract and tracer bullet
- [x] Define passive liveness/readiness behavior through public API tests
- [x] Add the first failing readiness test and minimal implementation
- [x] Preserve `/healthz` as traffic-free process liveness
- **Status:** complete

### Phase 35: Fault and cancellation acceptance
- [x] Inventory Phase 24 coverage and reject duplicate reliability tests
- [x] Add one public-interface regression at a time only for uncovered cancellation/fault behavior
- [x] Reconfirm classified 429/5xx/timeout behavior never becomes a local 500
- [x] Reconfirm restart-safe OAuth/config behavior already promised by v0.3
- **Status:** complete

### Phase 36: Bounded reliability harness and release handoff
- [x] Add a repeatable local fault-injection/soak command using only fake upstreams
- [x] Define observable pass/fail signals and a stop rule
- [x] Run full uv verification and one operator-authorized live smoke only
- [x] Update release documentation after behavior is proven
- **Status:** complete

### Phase 37: Public Agent tool-loop tracer
- [x] Specify one complete `/v1/responses` streaming tool-call and tool-result round trip
- [x] Add one failing public-interface tracer using only a fake Antigravity boundary
- [x] Make the smallest protocol change required for the tracer to pass
- **Status:** complete

### Phase 38: Agent compatibility reliability gate
- [x] Add the proven tool round trip to the bounded fake-upstream gate
- [x] Preserve thought signatures, call/result pairing, terminal SSE semantics, and lease cleanup
- [x] Keep the gate credential-free and network-free
- **Status:** complete

### Phase 39: Continuous verification and v0.5 release metadata
- [x] Add one GitHub Actions workflow using locked uv dependencies
- [x] Configure CI to run tests, compileall, reliability gate, and wheel build
- [x] Advance package/lock/docs/changelog to v0.5.0 only after behavior is proven
- **Status:** complete

### Phase 40: v0.5 acceptance and handoff
- [x] Run focused and full uv verification
- [x] Run the default bounded reliability gate and static/diff/secret checks
- [x] Review the final scope and report any live smoke intentionally not run
- **Status:** complete

### Phase 41: Unified CLI and doctor tracer
- [x] Specify public `hakimi serve` and `hakimi doctor` behavior through one test at a time
- [x] Keep configuration selection uv-only and compatible with `HAKIMI_CONFIG`
- [x] Make default diagnosis traffic-free, redacted, actionable, and machine-readable
- [x] Verify the running-instance version/readiness boundary without trusting system proxies
- **Status:** complete

### Phase 42: Explicit live account diagnosis
- [x] Add an opt-in live diagnostic path that reuses the existing layered credential health contract
- [x] Require an explicit account choice when more than one credential exists
- [x] Preserve manual-only Google traffic and safe upstream error classification
- **Status:** complete

### Phase 43: First-use Web UI state and generic integration handoff
- [x] Turn an empty installation into one obvious login-first path
- [x] Show one generic OpenAI-compatible Base URL/token/model handoff after readiness
- [x] Keep product-specific EMP guidance and additional pages out of the UI
- **Status:** complete

### Phase 44: v0.6 acceptance
- [x] Run focused/full tests, CLI subprocess smoke, Web UI parse, and reliability gate
- [x] Prove secrets never appear in doctor output or generated integration examples
- [x] Update version and release documentation only after the vertical slice is green
- **Status:** complete

### Phase 45: Unified deployment key
- [x] Make one operator-chosen key the Web login and downstream API key
- [x] Copy the authenticated key only on explicit user action; never render or return it from settings
- [x] Default browser persistence to the current session and keep persistent login explicit
- [x] Prevent unauthenticated deployment startup and provide a strong key generator
- [x] Update operator guidance and run focused/full security acceptance
- **Status:** complete

### Phase 46: Automatic first-start key provisioning
- [x] Generate and persist a strong deployment key when the selected config is missing or has no key
- [x] Show the generated key exactly on the provisioning start and reuse it on later starts
- [x] Fail closed if the private config cannot be written
- [x] Align first-start documentation and rerun CLI/full security acceptance
- **Status:** complete

### Phase 47: Antigravity quota visibility and metering correctness
- [x] Preserve cached-input and reasoning token details through non-streaming and streaming AGY conversion
- [x] Canonicalize routed AGY model variants for pricing and use current cached-input pricing
- [x] Expose cache/reasoning totals and clearly label equivalent API cost in the existing usage UI
- [x] Add manual, per-credential AGY quota refresh with bounded endpoint fallback and an in-memory last-result cache
- [x] Show model quota/reset snapshots in the existing credential card without background Google polling
- [x] Run focused/full tests, Web UI parsing, reliability gate, and diff/secret checks
- **Status:** complete

### Phase 48: Shared-window quota model and progress-bar UI
- [x] Reproduce the grouped `retrieveUserQuotaSummary` response and make it the primary quota contract
- [x] Preserve `fetchAvailableModels` only as an explicitly degraded availability fallback
- [x] Replace per-model quota rows with Gemini 5h and Weekly/7d shared-pool progress bars
- [x] Keep manual refresh, cached display, inference-health isolation, and responsive layout
- [x] Update operator documentation and run focused/full/reliability acceptance
- **Status:** complete

### Phase 49: Unified full verification and redacted evidence
- [x] Define one explicit, bounded Antigravity verification contract that reuses existing health, quota, Responses, and Agent seams
- [x] Add RED tests for staged API/CLI/Web results, safe failure classification, and report redaction
- [x] Implement local config, OAuth, control-plane, quota, non-stream, stream, and signed two-turn tool-call stages without background traffic
- [x] Produce a downloadable allowlisted report with structural protocol fingerprints only; never retain prompts, outputs, tokens, or credentials
- [x] Add offline fixture replay for the protocol fingerprint and verify deterministic pass/fail behavior without Google access
- [x] Run focused/full tests, compile/JS checks, reliability gate, and secret/diff review
- **Status:** complete

### Phase 50: Deterministic live verification tool turn
- [x] Add a regression that distinguishes the text probe from the tool-call probe
- [x] Force `list_files` only on the first streamed Agent turn and preserve an unconstrained final turn
- [x] Run focused, full, reliability, syntax, and diff verification without contacting Google
- [x] Receive operator confirmation of live Web full verification: three inference requests in 9,871 ms on 2026-08-30
- **Status:** complete

### Phase 51: NA2H Web identity, i18n, and themes
- [x] Replace browser-visible `hakimi-proxy` branding with `NA2H` while preserving the `hakimi` CLI and Python package
- [x] Add complete zh-CN/English translation for static and dynamic user-facing Web copy with a persisted preference
- [x] Add persisted system/light/dark theme selection with a system default and no-flash initialization
- [x] Verify responsive UI structure, inline JavaScript, focused/full tests, and documentation
- **Status:** complete

### Phase 52: Review and local candidate commit preparation
- [x] Review all pending source, test, and documentation changes against the accepted verification and Web scope
- [x] Correct reproduced verification boundary defects and retain regression coverage
- [x] Re-run automated checks and package verification; exclude private configuration, runtime data, and temporary artifacts
- [x] Prepare the explicit 16-file source, test, and documentation scope for the local commit
- [x] Preserve local-only delivery constraints: no push, tag, version bump, deployment, live inference, or service restart
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
| Candidate package build could not download `hatchling` in the sandbox | 1 | Retry the unchanged build with network approval and an isolated `/tmp` output directory |
| Temporary build-directory removal found a generated `.gitignore` after archive cleanup | 1 | Inspect the exact temporary directory, remove the task-created marker, and remove the empty directory |
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
| Phase 31 session-catchup could not lock the read-only default uv cache | 1 | Re-run once with `UV_CACHE_DIR=/tmp/na2h-uv-cache` and `--no-sync` |
| Two legacy credential-Test fixtures hit real preflight after staged health was added | 1 | Stub successful OAuth/control-plane stages so each test still isolates timeout or 429 inference behavior |
| Final documentation patch used a stale progress-file context | 1 | Re-read the file tail and apply the same update against the current text |
| Geju referenced an optional anti-pattern file absent from this installation | 1 | Continue from the complete main skill and output template; goudi risk references loaded successfully |
| First `/readyz` tracer returned 404 | 1 | Expected RED; add the minimal traffic-free route before specifying unavailable-state status |
| Empty-pool `/readyz` returned 200 | 1 | Expected RED; return a structured 503 only when the local ACTIVE count is zero |
| Authenticated app returned 401 for `/readyz` | 1 | Expected RED; add the non-secret readiness endpoint to the public health allowlist |
| OAuth persistence survey referenced nonexistent `tests/test_config.py` | 1 | Use the actual adapter/admin/main test files discovered by `rg --files` instead of repeating the path |
| Reliability-gate tracer could not import its module | 1 | Expected RED; implement the bounded fake-upstream module behind the specified `run_gate` interface |
| Planning-file search ran from the aggregate workspace instead of the repository | 1 | Re-run from `NotAccess2Hakimi`, where the maintained planning files live |
| Default reliability gate flooded the tool output with per-request INFO logs | 1 | Make the CLI quiet by default, then retry at a smaller bounded scale before the 500-request default |
| Inline Web UI parser command over-escaped its JavaScript regular expression | 1 | Retry with deterministic `<script>` string splitting instead of shell-sensitive regex syntax |
| RTK path-filtered documentation diff was parsed as a bad Git revision | 1 | Inspect the full compact diff and targeted file contents instead of repeating the ambiguous invocation |
| No NA2H process was listening on the configured local port for final smoke | 1 | Start the current checkout on an isolated temporary port, make one authorized request, then stop it |
| Local smoke client inherited the system HTTP proxy and could not reach loopback in the sandbox | 1 | Disable environment proxy use for the localhost client only; keep the NA2H server's configured upstream proxy unchanged |
| Proxy-free local smoke client was still denied loopback sockets by sandbox policy | 2 | Request the narrow loopback/network permission required for the one final live smoke; do not change application code |
| Escalated client could not see the server in the restricted network namespace | 3 | Stop retrying the split topology; co-locate server and client in one authorized process, then shut it down deterministically |
| First co-located live inference used only 32 output tokens and AGY returned no visible output | 1 | NA2H correctly returned `502 empty_upstream_response`; retry once with the previously proven 512-token tiered-model budget |
| Planning skill installation has no `check-complete.py` helper at the documented script path | 1 | Verify completion directly from the Phase 34-36 checkboxes and repository acceptance evidence |
| v0.5 reliability tracer lacked `agent_tool_round_trip` | 1 | Expected RED; implement the public two-turn AGY scenario behind the existing bounded gate result |
| First Agent tracer implementation reached validation with a mismatched result | 1 | Inspect the isolated public result fields before changing protocol code; do not weaken the expected contract |
| Local `uv build` could not fetch isolated Hatchling requirements in the network sandbox | 1 | Re-run the same package build with narrow dependency-download permission; CI remains responsible for clean hosted resolution |
| CLI-focused test tried to rebuild after adding the console script and could not fetch Hatchling in the sandbox | 1 | Reuse the already locked environment with `uv run --no-sync` for behavior tests; reserve an authorized clean build for final acceptance |
| Health auth-state test patch used an inferred stale assertion block | 1 | Read the exact current test and add the same public boolean assertion at the actual health response boundary |
| Installed `hakimi --help` check could not lock the read-only default uv cache | 1 | Re-run once with the existing task-specific writable cache and `--no-sync`; the installed console surface passed |
| RTK-filtered OpenAPI curl truncated JSON before jq parsing | 1 | Use documented `rtk proxy curl` only for the complete local response; final version/UI markers passed |
| Non-loopback CLI RED test entered the real server loop | 1 | Add an import-boundary failure so the missing security guard fails immediately without starting Uvicorn |
| New serve tests leaked `HAKIMI_CONFIG` into the full suite | 1 | Register the variable with pytest monkeypatch so teardown restores the environment before later app creation |
| Phase 46 full suite loaded generated auth in a later diagnostic test | 1 | `delenv(..., raising=False)` did not register an absent key; seed it through `setenv` so pytest restores the original environment after each CLI test |
| Final isolated package build could not reach PyPI in the sandbox | 1 | Re-run the unchanged `uv build` with dependency-download permission; v0.6.0 wheel and sdist built successfully |
| Phase 47 cache invalidation landed in the AI Studio update route | 1 | Move the statement to the Antigravity OAuth-identity update branch and keep AI Studio behavior unchanged |
| Combined Phase 47 code/test/error-log patch used the wrong file context | 1 | Split production/test repair from the planning-log append and apply each against its exact file |
| Looked for a nonexistent `tests/test_usage.py` while adding public usage coverage | 1 | Locate the existing `/v1/usage` acceptance in `tests/test_routes.py` and extend that real boundary instead |
| Phase 49 replay accepted a passing report with a false signature invariant | 1 | Expected RED; validate the passing Agent evidence before declaring an offline report structurally valid |
| Phase 49 admin verify route was absent | 1 | Expected RED; expose the verified core through one authenticated Antigravity credential route |
| `hakimi verify` was rejected by argparse | 1 | Expected RED; add the bounded local-API client command and offline replay mode |
| Phase 49 Web UI lacked the full-verification action | 1 | Expected RED; add the manual per-Antigravity-card control, inline result, and client-side report download |
| Full verification marked an empty non-stream response as passed | 1 | Expected RED; make visible output a required structural invariant for that stage |
| Full verification marked an unsigned streamed tool call as passed | 1 | Expected RED; require a function call plus a native or detached thought-signature carrier |
| Full verification marked an empty Agent replay as passed | 1 | Expected RED; require visible final output after the tool result is accepted |
| Offline replay accepted a passing report with a false non-stream fingerprint | 1 | Expected RED; validate the fixed passing stage set, summaries, and allowlisted response fingerprints |
| Full verification reported passed with a selected-account lease leak | 1 | Expected RED; scope leak evidence to the pinned account and make any residual lease fail the report |
| Focused suite read one stale usage row from `/tmp/hakimi_test_routes.db` | 1 | The new pinning test reused a fixed legacy fixture DB; isolate it with `tmp_path` and remove only the task-created temp DB |
| Verification-command search included a nonexistent `scripts/` path | 1 | Use the maintained README and CI workflow as the authoritative command sources |
| Live full verification allowed the model to answer text instead of calling the declared tool | 1 | Separate the text/tool prompts and force `list_files` only on the first streamed Agent turn |
| Headless Chrome was terminated by the managed sandbox before writing a screenshot | 1 | Re-run the same local-file visual check with narrow browser permission; desktop and mobile renders then succeeded |
| Parallel final JavaScript parse over-escaped the inline-script regular expression | 1 | Re-run the previously proven Node parser with one shell-escape layer; no application code change required |
| Final line-number search left Markdown backticks unquoted for the shell | 1 | Re-run the read-only search with a single-quoted pattern; no repository command or application behavior was affected |
| Candidate review reproduced a retained credential lease after the verifier stream exceeded its byte limit | 1 | Add explicit iterator cleanup around bounded stream consumption and retain a real-pool regression |
| Replay crashed on a non-object stage in a passing report and accepted the same malformed failed report | 1 | Validate every stage as an object before status-specific replay checks; return the existing invalid-report error path |
