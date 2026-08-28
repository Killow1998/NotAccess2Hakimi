# Findings & Decisions

## Requirements

- Do not access or work around the suspended AGY service.
- Keep Hakimi moving through AI Studio.
- Validate the real EMP provider path without exposing credentials.
- Complete AGY protocol behavior for credentials the operator owns and is authorized to use.
- Do not save, refresh, or test the credentials pasted in chat; use mock fixtures and a sanitized ignored local file path.

## Research Findings

- Hakimi is clean on `main` at `9e38104` and already implements an OpenAI Chat Completions facade.
- EMP has a dirty user worktree; its 61-test suite passed in the prior inspection.
- EMP currently has an enabled Gemini AI Studio provider and a configured `gemini-3.7-flash` model.
- AGY CLI 1.1.15 returns a product eligibility 403; appeal is an external manual action.
- AI Studio account discovery returned 37 models and includes `gemini-3.7-flash`.
- Two real non-streaming `gemini-3.7-flash` requests succeeded through Hakimi.
- The first real stream exposed duplicated SSE framing; the shared adapter/route contract was fixed test-first.
- Two post-fix `gemini-3.7-flash` stream attempts reached Google but returned upstream 503; use `gemini-3.6-flash` as a control rather than repeatedly hitting the same unavailable path.
- A real `gemini-3.7-flash` forced function call succeeded through Hakimi.
- `gemini-3.6-flash` streaming succeeded through the same Hakimi path, proving the SSE fix against a real upstream.
- An EMP-to-Hakimi 3.7 request reached Hakimi but Google returned 503; use 3.6 as the integration control after the credential cooldown expires.
- The current AGY adapter hard-codes `rising-fact-p41fc`, while `AntigravityCredential` has no persisted project field.
- The existing OpenAI-to-Gemini conversion handles only system text, user/model text, and three generation settings; it drops tool definitions/calls/results, images, and thought signatures.
- The current Gemini-to-OpenAI response and stream conversion emits text only and always finalizes the route with `stop`; it cannot preserve tool-call deltas or upstream finish reasons.
- The existing loader already supports `HAKIMI_CONFIG`; no second loader is needed. A local-only `config.local.yaml` placeholder can therefore organize future authorized credentials without reading or overwriting the existing private `config.yaml`.
- Existing uncommitted AI Studio streaming fixes change the adapter contract to return an SSE payload without the `data:` prefix. AGY work must preserve that route-level framing contract.
- CLIProxyAPI's current control-plane flow calls `v1internal:loadCodeAssist` with `metadata.ideType=ANTIGRAVITY`, accepts project keys `cloudaicompanionProject`, `projectId`, or `project` (including `{id: ...}`), and calls `v1internal:onboardUser` only when no project is returned.
- CLIProxyAPI chooses the default allowed tier, falls back to the current tier and then `free-tier`; onboarding polls up to five times and extracts the project only after `done=true`.
- CLIProxyAPI's Antigravity request translator keeps the native Gemini request inside an envelope, normalizes tool declarations to `parametersJsonSchema`, groups function calls/responses, sanitizes thought signatures, and restores function names on responses.
- Hakimi exposes OpenAI Chat Completions rather than native Gemini, so copying CLIProxyAPI's full Gemini-to-Gemini machinery would be needless. The focused implementation should map only Chat Completions fields that Hakimi actually accepts and preserve AGY's envelope/project behavior.
- Google's current thought-signature documentation defines the Chat Completions carrier as `tool_calls[].extra_content.google.thought_signature`; it must be returned on the same function-call part, especially for Gemini 3 tool loops.
- Native Gemini responses attach `thoughtSignature` to a content part. For parallel calls only the first call normally carries it; response conversion must not invent, merge, or copy it to sibling calls.
- Official guidance requires preserving the complete function-call model message before tool responses. Hakimi therefore needs stable tool-call IDs plus a request-side ID-to-name lookup for `role=tool` messages.
- The current lock resolves FastAPI 0.141.1 and Starlette 1.6.0. Starlette's installed `TestClient` and current official docs require `httpx2`; both its deprecated `httpx` fallback and the installed `httpx2` blocking portal hang on the first route request in this environment.
- The faulthandler trace shows the sync test thread blocked in `TestClient.handle_request` while the AnyIO portal event loop is idle. Starlette's official alternative is `httpx2.AsyncClient` with `ASGITransport`, which avoids the blocking portal entirely.
- Final code review found two acceptance-path gaps: provider selection always preferred AI Studio even for an `antigravity/...` model name, and adapter `post()` calls buffered SSE responses before returning them to the route.
- The existing local `config.yaml` remains ignored, contains no test fixture markers, and is now mode `0600`; application saves must enforce the same mode for newly created files.
- Final verification: 63 tests passed, Python compilation and `git diff --check` passed, and tracked files contained none of the supplied access-token/vendor/project markers.
- Earlier AGY phases intentionally used `httpx.MockTransport` because the supplied credential was exposed. Phase 20 is the separately authorized local-runtime acceptance run described below; no credential value is recorded here.
- The Credentials page has only add, update, delete, and list actions; there is no test button or test API.
- The green `ACTIVE` badge is the credential pool's default schedulable state, not proof that OAuth refresh or model inference succeeded.
- Testing through `/v1/chat/completions` cannot guarantee which credential is selected when a pool contains multiple entries, so the missing action needs a credential-specific admin endpoint.
- Both adapters already expose the required `forward()` seam. The test endpoint can reuse it with the exact `PooledCredential`, a tiny non-streaming prompt, and the existing proxy setting; no new adapter abstraction or dependency is needed.
- The implemented test action targets the selected credential directly, uses `gemini-3.7-flash`, closes upstream resources, and reports success or the upstream/connection failure through the existing toast UI.
- The reported Test failure occurs almost exactly 30 seconds after `Refreshing OAuth token`, matching the explicit OAuth timeout rather than an upstream 401/403 response.
- `config.local.yaml` currently has an empty `proxy`, so the failing refresh attempts a direct connection. The empty exception text is consistent with `httpx.ConnectTimeout`, whose class name the Test endpoint currently omits.
- Earlier acceptance evidence in the planning records proves AI Studio and EMP-to-Hakimi model traffic, while AGY was explicitly left untested. The exact earlier proxy invocation still needs to be recovered before changing connectivity code.
- The root prior-session rollout contains the `EMP_HAKIMI_OK` success marker together with explicit SOCKS and `HAKIMI_CONFIG` calls; structured extraction is being used to avoid printing any credential values from that history.
- Historical acceptance results confirm that real AI Studio requests and the EMP-to-Hakimi 3.6 control succeeded. They do not prove AGY OAuth connectivity; that path was deliberately untested at the time.
- Exact prior-session commands show every successful/meaningful external check explicitly set HTTP and SOCKS proxy variables to `127.0.0.1:7897`. The current Hakimi local config omitted that proxy, reproducing the earlier EMP connectivity mistake.
- A credential-free HEAD probe through `http://127.0.0.1:7897` reached Google's OAuth host in about 0.62 seconds and received HTTP 404, proving the proxy path is currently live.
- The Hakimi edit modal intentionally leaves masked credential fields empty, but its PUT models currently require and replace every secret. This is the concrete cause of the confusing edit behavior and can corrupt a working credential during partial edits.
- For this local admin UI, the safer pattern is not to return stored secrets to the browser: blank secret inputs should mean "keep the existing value", with explicit placeholder/help text.
- EMP's current UI is a single max-width page with stacked semantic sections, table-based actions, one reusable modal, a fixed status notice, disabled busy buttons, responsive one-column fallback, and Chinese-first labels.
- EMP explicitly presents stored-secret state (`api_key_set` / credential saved) while edit forms say that blank secret fields keep the existing value. Hakimi currently does the opposite at the interaction boundary: masked fragments are shown, but blank edit fields overwrite values.
- EMP backs that interaction with `merge_web_update()` and `public_config()`: omitted/masked keys retain existing values, the browser receives only secret-set state, and tests lock down the contract. NA2H should copy this semantic boundary, not EMP's encrypted secret-store implementation, because NA2H already has a private mode-0600 YAML contract and secret-storage migration is outside this UX task.
- EMP's implementation has limits worth improving rather than copying: it posts the whole public config, relies on a masked-string sentinel, uses one global notice that concurrent actions can overwrite, and falls back to horizontally scrolling tables on small screens. NA2H can keep item-specific update endpoints, explicit secret-set booleans, and per-credential test state while adopting the single-page information architecture.
- The landing boundary is deliberately narrow: preserve Hakimi's single static HTML architecture and existing YAML/SQLite/API surfaces; do not add a frontend framework, persistent UI state, test history, or a database migration.
- Official CLIProxyAPI issue #1015 reports token refresh/model discovery success followed by Antigravity generation `429 RESOURCE_EXHAUSTED` on both daily and production endpoints, with no confirmed maintainer fix or reliable `Retry-After` header; this matches the current NA2H logs after the daily 404 fallback.
- CLIProxyAPI issues #2831 and #3655 discuss honoring `quotaResetDelay`, `quotaResetTimeStamp`, and `RetryInfo.retryDelay` for cooldown scheduling, but are closed without an accepted fix; NA2H should expose those fields for diagnosis and avoid aggressive retries.
- A single metadata-only probe using the active local runtime config returned `loadCodeAssist=200` and `fetchAvailableModels=200` from daily. The returned catalog included `gemini-3.6-flash-high`, `gemini-3.6-flash-medium`, `gemini-3.6-flash-low`, `gemini-3.6-flash-tiered`, and `gemini-3.7-flash-tiered`, but not `gemini-3.7-flash-high` or a base `gemini-3.7-flash` ID.
- The live catalog confirms the X discussion is mixing display names and physical IDs: use `gemini-3.7-flash-tiered` for the current 3.7 entry, and use `gemini-3.6-flash-high` when explicitly requesting the 3.6 High tier. Do not silently map an unobserved 3.7 High ID to another model.
- Antigravity Manager's current model router also prioritizes raw account quota-model IDs and user-defined mappings rather than hardcoding every new Flash variant; this supports catalog-driven handling over speculative aliases.
- `BearerAuthMiddleware` normalized the root URL with `rstrip("/")`, turning `/` into an empty string; with bearer auth enabled this prevented the public UI and its login form from rendering. Normalizing with `rstrip("/") or "/"` restores the intended public-path contract.
- Live acceptance now proves OAuth refresh `200`, Antigravity `generateContent` `200`, and a non-streaming `/v1/responses` request returning visible `output_text: "OK"` with `gemini-3.7-flash-tiered`. The earlier empty result was caused by a 32-token test budget and later upstream `429` throttling, not by the Responses converter.
- EMP's `context 0` and `reasoning medium` after Hakimi model discovery are fallback metadata: Hakimi's generic `/v1/models` entries currently expose only OpenAI model fields, while EMP assigns `context_window=0` and `reasoning_levels=["medium"]` when those fields are absent. This means unknown context and default reasoning metadata, not an AGY capability claim; live Responses SSE already works.
- The verified Gemini 3.7 Flash limits are a 1,048,576-token context window and 65,536 maximum output tokens; supported thinking levels are low, medium, and high, with minimal unsupported. The local EMP model entry now records the context window and supported levels.
- End-to-end live acceptance passed in Codex using `hakimi/gemini-3.7-flash-tiered`; both high and medium effort were selected successfully, and Codex displayed the expected approximately 996K context window.

## Responses API Work

## Codex Tool-Call Diagnosis (2026-08-20)

- EMP is not the primary fault boundary for the empty Codex turns: its `responses` provider forwards the request and stream unchanged, and both EMP and NA2H returned HTTP 200 in the captured run.
- A real Codex 0.147.0 request placed tools in `input[0]` as `{"type":"additional_tools","tools":[...]}`. The first namespace was `functions`, containing `exec` as a Responses `custom` tool plus regular function tools such as `wait`.
- The top-level Responses `tools` field was absent/null. NA2H `routes/responses.py::_tools()` only reads `body["tools"]` and accepts `type == "function"`, so the complete Codex tool registry is discarded before the Gemini request.
- The same Codex CLI accepted a local fixed Responses stream, proving the basic EMP/Responses transport and completion framing. The failing real thread completed without a final agent item because the model had no usable tool declaration for the file-reading request.
- The minimal repair belongs in NA2H's Responses facade: normalize `additional_tools` namespaces into the internal tool representation, retain custom-tool identity/arguments, and add a regression before changing the adapter or EMP.
- The Codex custom-tool probe confirmed the accepted stream sequence: `response.output_item.added` with `type=custom_tool_call`, one or more `response.custom_tool_call_input.delta` events, `response.output_item.done`, and `response.completed`. The next request contains `custom_tool_call` and `custom_tool_call_output` input items.
- NA2H now maps custom tools to a single JSON `input` parameter for the existing Chat/Gemini tool path, unwraps that parameter on Responses output, and preserves regular function tools unchanged. Custom input deltas are emitted once the complete Chat tool-call arguments are available, avoiding invalid partial JSON.

- NA2H currently exposes `/v1/chat/completions` only; its AGY adapter already handles tool calls, thought signatures, multimodal content, and streaming at that boundary.
- The smallest Codex bridge is to translate Responses requests into the existing internal Chat Completions body and translate results back, without changing the AGY adapter.
- Keep `/v1/chat/completions` stable; `/v1/responses` is an additive facade, not a replacement.
- EMP's custom Provider contract is `base_url` plus `protocol`; for NA2H use `protocol=responses`, `auth_mode=api_key`, and a Base URL ending in `/v1` so EMP appends `/responses`.
- EMP's model discovery sees NA2H's raw model IDs. To force AGY when NA2H also has AI Studio credentials, set the EMP model `upstream_id` to `antigravity/gemini-3.7-flash-tiered`; EMP forwards that exact ID and NA2H's provider prefix selects AGY.
- EMP's generic model parser already accepts provider-advertised `context_window`, `max_input_tokens`, `output_limit`, `supports_reasoning`, `reasoning_levels`, `architecture.input_modalities`, `architecture.output_modalities`, `supported_parameters`, `streaming`, and per-field `capability_sources`. NA2H should emit that contract directly instead of asking EMP to recognize a loopback URL as Google's official endpoint.
- Normal `python -m hakimi_proxy.main` currently forces Uvicorn reload. Because Web UI credential mutations persist `config.local.yaml`, WatchFiles restarts the process and repeats initialization logs. Stable runtime and development reload must be separate commands.
- The active local port is a user configuration fact (`config.local.yaml: port: 8000`), while `12345` is only the repository default. EMP should follow the active endpoint rather than forcing both projects to share a hard-coded port.
- The implemented EMP contract test uses EMP v0.8.0's real generic parser, not a duplicated schema assertion. It retains the tiered model's 1,048,576 context, 65,536 output, low/medium/high reasoning, text/image input, tools, structured output, and streaming.
- Capability discovery must describe the intersection of model and gateway behavior. NA2H therefore publishes text/image for models whose official catalog also supports audio/video until the Responses facade implements those additional input carriers.

## Technical Decisions

| Decision | Rationale |
|----------|-----------|
| Treat a real successful request as model availability truth | Static model lists and public documentation may lag account-specific rollout |
| Keep credentials in existing encrypted storage and temporary files only | Avoid copying secrets into tracked Hakimi files |
| Standardize Hakimi on Python 3.11 and uv-only | Match EMP and remove an unnecessary environment manager/runtime split |
| Reuse the existing `HAKIMI_CONFIG` loader | A local placeholder can use a different filename without adding code or touching the existing private config |
| Make onboarding opt-in per credential | `loadCodeAssist` is discovery, while `onboardUser` changes external account state and must be explicitly authorized |
| Implement only Chat Completions mappings | Hakimi has one public inference surface; copying a multi-protocol translator would add unneeded code and maintenance |
| Add `httpx2` only to the dev extra | It supports Starlette's current async ASGI testing path without replacing the application's established runtime `httpx` client |
| Use provider prefixes only as explicit routing hints | Keep the existing bare-model AI Studio preference while making `antigravity/<model>` deterministic |
| Use `client.send(..., stream=stream)` in both adapters | Preserve the current interface while making SSE genuinely incremental instead of buffered |
| Carry AGY thought signatures in Responses `extra_content.google` | Gemini 3 requires the signature on the replayed function-call part; dropping it makes the next tool turn fail with HTTP 400 |

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| AGY account suspended | Freeze AGY path pending official appeal |
| Newly supplied credential is exposed and described as a third-party finished account | Refuse login/use; keep implementation credential-agnostic and tests offline |
| Existing dirty adapter/test files overlap shared streaming behavior | Preserve the established payload-only contract and limit AGY edits to its adapter, config/example, tests, and docs where necessary |

## AGY Tool-Loop Diagnosis (2026-08-20)

- A local uv NA2H instance reproduced the screenshot failure: the first stream reached AGY with HTTP 200, while the next tool-history request returned HTTP 400 and NA2H surfaced 503 after retries.
- The upstream error was `Function call is missing a thought_signature in functionCall parts`, identifying a lost protocol field rather than an EMP transport or context-window problem.
- `_gemini_to_openai` already preserved the signature on Chat tool calls, but the Responses converter dropped it from `function_call`/`custom_tool_call` output items; `_messages` therefore could not replay it.
- The minimal fix keeps only the validated `extra_content.google.thought_signature` shape, attaches it to both regular and custom Responses tool items, restores it to Chat history, and carries it through Responses SSE output.
- Regression coverage now includes regular/custom history and non-streaming/streaming output. Focused Responses tests pass (13), and the full NA2H suite passes (91).
- Real authorized local-runtime checks passed for a non-streaming custom-tool two-turn loop and a streaming custom-tool two-turn loop: first and second requests were HTTP 200, with the first output carrying a signature and the second producing a normal message.
- The public CLIProxyAPI reference confirms two relevant invariants: detached Responses reasoning must be reattached to the next function call, and Gemini function-call/function-response parts need stable IDs for pairing. NA2H adopts only those narrow invariants; its existing Chat facade remains the protocol boundary.
- The tracked legacy environment-manager file was removed; the hidden-file scan is clean. Startup and verification use `uv` only.

## CPA-Aligned Tool History Pairing (2026-08-20)

- `/tmp/cliproxyapi-ref` was used as a read-only public reference; it is not part of the repository.
- NA2H now preserves detached AGY thought signatures as standard Responses `reasoning.encrypted_content` items, including streaming chunks and multiple carriers.
- NA2H now forwards `functionCall.id` and `functionResponse.id` in the Gemini envelope. Missing response IDs were the remaining cause of the reproduced second-turn `400` after the carrier fix.
- Focused adapter/Responses tests pass (44); the full NA2H suite passes (97).
- Real authorized low-reasoning checks pass: non-streaming tool loop `200 -> 200`, streaming tool loop `200 -> 200`; both second turns return a normal message.

## Antigravity OAuth and Refresh (2026-08-20)

- The official `google-antigravity/antigravity-cli` GitHub repository currently exposes README, installation/authentication documentation, releases, and changelog; its agent implementation is not published. The README documents system-keyring storage, browser Google Sign-In, and SSH/manual URL handling.
- Google OAuth access tokens are short-lived; refresh tokens are long-lived but can be revoked, expire, or be invalidated by account/client limits. “12-hour logout” therefore cannot be fixed by an unconditional keepalive loop.
- NA2H now refreshes on demand five minutes before access-token expiry, serializes refreshes per account, persists rotated refresh tokens, and turns `invalid_grant` into a re-authorization message.
- The Web UI now starts a local OAuth authorization-code flow on callback port `51121`, validates a random state, fetches the account email, and creates the credential without manual client ID/secret/refresh-token entry. Manual entry remains as a headless fallback.
- The implementation deliberately does not spoof undocumented fingerprints or run periodic background refresh traffic; those would add detection/rate-limit risk without improving OAuth correctness.

## Phase 23: Remote OAuth and Streaming Failover (2026-08-20)

- The current OAuth manager binds the callback listener to `127.0.0.1` and the UI only polls for the local callback; remote browser use therefore needs a manual callback URL/code submission seam.
- The manual path must keep the server-generated `state`, accept a full callback URL or one-time code, and reuse the existing token exchange; it must never accept refresh tokens from the browser.
- `routes/chat.py` currently returns a `StreamingResponse` after an HTTP 200 and emits an initial assistant chunk before reading the upstream body. A transport/body failure before the first valid upstream event is therefore not eligible for retry.
- The smallest streaming fix is a first-event gate in the shared stream adapter path; after the first valid event, emit a normalized SSE error rather than retrying after downstream output has begun.
- Implemented the remote completion seam by parsing only localhost callback URLs and requiring the server-owned session state; code-only submission still uses the state from the active session.
- The stream gate replays prefetched lines through the same adapter transform, so the public adapter contract and SSE framing remain unchanged.
- Responses SSE now stops before `response.completed` when the shared Chat stream emits a normalized post-start error.
## Phase 24: Reliability contract (2026-08-20)

- `CredentialPool.get_available()` only updates LRU state; it has no in-flight accounting or wait boundary, so concurrent requests can select a credential already serving a long stream.
- `routes/chat.py` retries every non-200 response except 401/403/429/5xx specially; a terminal 400 can therefore be sent repeatedly until `max_retries` is exhausted.
- Streaming leases must outlive route return and be released from the `StreamingResponse` generator's `finally`; non-streaming and admin Credential Test paths need the same shared lifecycle.
- Current `/api/credentials` already exposes pool state and cooldown data; Phase 24 should add only safe runtime health fields and minimal card feedback, with no new page or quota model.
- Phase 24 policy is fixed by user choice: one in-flight request per credential, 30-second bounded wait, single Uvicorn process, mock-only automated verification.
- Phase 24 result: `/healthz` now reports `in_flight_requests`; `/api/credentials` and the existing single-page UI expose health, cooldown, latency, in-flight, and safe last-error fields. Runtime state is intentionally in-process and resets on restart.
- Terminal 4xx responses fail once as `upstream_request_error`; 429/5xx and transport failures can fail over; invalid JSON and empty 2xx responses return 502-class errors instead of silent success.

## Codex unsigned tool-history replay (2026-08-27)

- Rollout `01a04263-fbe0-7770-9427-65f9199722ec` completed its first AGY custom
  tool call but recorded no Responses reasoning carrier or provider signature;
  the next request therefore replayed an unsigned Gemini `functionCall` and
  received HTTP 400.
- The image input was not the failing boundary: AGY accepted the first request
  and emitted the tool call. OAuth refresh was also unrelated because the
  request reached `streamGenerateContent` and received an application response.
- Current CPA sanitizes synthetic Gemini history by adding
  `skip_thought_signature_validator` only to the first unsigned function call
  in each model turn. Native signatures are preserved and later parallel calls
  remain unsigned. NA2H now applies the same narrow rule during conversion.
- NA2H separately tried to call `.json()` on an unread streaming response, so
  `httpx.ResponseNotRead` hid the real upstream 400 and became a local 500.
  Streamed error bodies are now buffered up to 64 KiB before classification.
- Post-fix live acceptance completed model switching, image input, compaction,
  resume, repeated custom-tool calls, tool outputs, and a final `ls + README`
  task without a protocol error. This validates the full
  Codex-to-EMP-to-NA2H-to-Antigravity round trip, not only an adapter unit test.

## Server portability landing decision (2026-08-27)

- Current remote OAuth completion is functionally usable, but `start()` always
  binds `127.0.0.1:51121`; a server/container can therefore fail before the
  copy/paste flow begins even though remote completion needs no listener.
- Credential portability has no first-class API or UI. `/v1/usage/export`
  exports metering records only; moving accounts currently means copying the
  secret-bearing YAML and optionally the SQLite database by hand.
- The minimum viable server slice keeps one in-memory OAuth session and one
  worker, but makes local versus remote callback behavior explicit. Multi-user,
  multi-worker session persistence, Docker packaging, and background quota
  polling are deferred until this slice proves the deployment path.
- Credential bundles must be versioned and credentials-only. They must exclude
  short-lived access tokens, proxy settings, downstream bearer auth, runtime
  health, and usage records. Secret export is allowed only over loopback or
  HTTPS and must use `Cache-Control: no-store`.
- AGY health must be layered: passive request health remains traffic-free;
  active OAuth/control-plane checks are manual; generation remains an explicit
  full Test. No periodic keepalive or high-frequency status polling is added.
- The public UI should keep one OAuth action. It selects local automatic mode
  only when the browser itself opened Hakimi through a loopback hostname;
  domain/IP access uses listener-free remote completion. Both modes retain the
  copied callback URL fallback. The API keeps an explicit mode for tests and
  non-browser clients, with body-less requests defaulting to remote.
- `_OAuthSession` can carry a mode field without changing code exchange: both
  modes must use the registered localhost redirect URI, while only local mode
  instantiates `_CallbackServer`.
- Credential import/export can stay inside the current YAML contract: a pure
  bundle module validates all input and builds replacement credential lists,
  while the admin route owns HTTPS/loopback enforcement, persistence, and pool
  reload. This avoids coupling secret parsing to browser or runtime state.
- A single “凭证迁移” modal keeps the credential toolbar compact. It downloads
  a clearly marked sensitive JSON backup and performs import preview before an
  explicit skip/overwrite apply; secret values are never rendered in the UI.
- The existing Test endpoint already owns the exact-credential lease, failure
  classification, cooldown/disable actions, and full inference probe. Health
  should deepen that one action instead of adding another button or scheduler.
- AGY staging can be explicit with one adapter control-plane seam: refresh the
  OAuth token, call `loadCodeAssist` even when a project is cached, then run the
  existing generation probe. The route records `local`, `oauth`,
  `control_plane`, and `inference` stages; AI Studio retains an inference-only
  check.
- The staged route can preserve all existing 429/auth/transport state actions
  by converting non-200 stage responses into the same `UpstreamError` path.
  The only new public data is the failed stage and per-stage latency; no token,
  project payload, or raw upstream body is returned.
- The final operator check passed all four stages—local, OAuth, control-plane,
  and inference—in 13,668 ms after restarting the updated application.

## v0.4.0 reliability direction (2026-08-27)

- The product target is a provider-neutral, unattended single-node Gemini
  gateway, not a client-specific dashboard or a multi-tenant SaaS in this phase.
- Current `/healthz` always returns `status: ok`; the first public contract to
  prove is a traffic-free `/readyz` that distinguishes process liveness from
  whether at least one credential is locally schedulable.
- Reliability work must preserve one-worker/in-memory scheduling, avoid Google
  background traffic, and use public API behavior plus fake upstream boundaries.
- Multi-user keys, distributed workers, quota prediction, per-credential
  concurrency increases, and another WebUI redesign are outside v0.4.0.
- Phase 24 already added lease, failover, terminal-error, empty-output, and
  stream-cleanup regressions. v0.4 must inventory those observable contracts
  before adding tests; duplicating them would create maintenance, not evidence.
- The first genuine gap remains readiness: `/healthz` is liveness and always
  reports `ok`, while no public endpoint distinguishes an empty/fully
  unavailable credential pool without contacting an upstream.
- Existing public route regressions already prove pre-first-event failover,
  post-first-event normalized errors, terminal 400 classification, 429
  failover, empty/invalid upstream rejection, successful-stream lease release,
  and eight-request single-flight serialization. The uncovered cancellation
  case is an actual client disconnect while a stream is still open.
- `/readyz` should be public like `/healthz`, return 200 when at least one
  credential is in the ACTIVE state, and return 503 when none is active. A busy
  ACTIVE credential still means the process can accept a bounded queued request;
  readiness must not flap with every in-flight lease.
- Starlette's current `StreamingResponse` listens for `http.disconnect` under
  ASGI spec 2.3 and cancels its streaming task. A public ASGI request can
  therefore reproduce a real mid-stream disconnect without opening a socket or
  calling NA2H's private stream generator directly.
- The public ASGI disconnect regression passes without production changes:
  after meaningful output, cancellation closes the upstream response and the
  pool reports `in_flight=0`. The cancellation mechanism was already correct;
  v0.4 adds evidence rather than another cleanup layer.
- Public Chat route coverage still lacks direct 5xx and transport-timeout
  assertions. Both are already classified as retryable cooldown failures and
  should finish as structured 503 responses, never local `proxy_error` 500s.
- New public regressions confirm upstream HTTP 503 and `ConnectTimeout` both
  finish as classified 503 responses and put the affected credential into
  cooldown; neither becomes a local 500.
- Existing adapter coverage proves concurrent refresh is single-flight and a
  rotated refresh token reaches the credential object. The remaining restart
  question is whether the configured persistence callback writes that rotated
  value and a fresh config load recovers it.
- `create_app()` binds the adapter update callback to `save_config`, and the
  pool holds the same credential object as `app.state.config`. A lifecycle
  regression can therefore prove restart recovery without adding a persistence
  abstraction or exposing any token through an HTTP response.
- The lifecycle regression passes: a rotated refresh token is written through
  the real application callback, survives `load_config`, and retains mode 0600.
  No production persistence change is required.
- A standalone reliability gate must isolate its SQLite config and diagnostics
  under a temporary working directory before importing/creating the app;
  otherwise a fake-upstream test could still append local operational files.
- A 500-request gate cannot use the application's normal INFO verbosity as its
  automation contract: `httpx` emits one line per synthetic request and hides
  the actual verdict. The CLI should emit one JSON summary by default while
  leaving library/test logging behavior unchanged.
- The default bounded gate passes 500/500 requests at concurrency 8 with one
  maximum real upstream coroutine, zero leaked leases, ready HTTP 200, and the
  intended 429-failover/503/timeout public matrix. This is the release stop
  signal: any mismatch raises and returns a nonzero command status.
- Live tiered-model acceptance needs a realistic output allowance: 32 tokens
  produced a valid upstream 200 with no visible output and NA2H correctly
  returned `502 empty_upstream_response`; 512 tokens completed with exact `OK`.

## v0.5.0 Agent compatibility direction (2026-08-28)

- NA2H's critical product contract is a complete Codex Agent session, not more
  credential-management surface. Existing tests cover individual conversion
  behaviors, while the v0.4 reliability gate exercises only simple text output.
- The first v0.5 proof must cross the public `/v1/responses` interface twice:
  stream a signed tool call, then replay its tool result and finish with visible
  assistant text. Fake upstream I/O is the only permitted mock boundary.
- The existing single-worker, one-flight-per-credential runtime remains the
  release contract. Multi-user keys, quota prediction, additional provider
  aliases, higher per-account concurrency, and Web UI redesign stay out of v0.5.
- There is no repository CI workflow today, so the proven fake-upstream gate is
  not automatically enforced on pushes. CI belongs after the public tracer is
  green, not before it.
- Astral's current official GitHub Actions guide (checked 2026-08-28) pins
  `astral-sh/setup-uv` v9.0.0 at commit
  `c771a70e6277c0a99b617c7a806ffedaca235ff9` and `actions/checkout` v7.0.1 at
  `3d3c42e5aac5ba805825da76410c181273ba90b1`. Use these immutable commits with
  `contents: read`, not floating tags.
- The current verified local toolchain is uv 0.11.1. CI should pin that exact uv
  version for reproducibility while the setup action itself remains pinned to
  the current immutable v9 commit. `dist/` is already ignored, so local wheel
  verification will not pollute the checkout.
- The public Chat route creates its upstream `httpx.AsyncClient` at request
  time, while `AntigravityAdapter.forward()` owns real OpenAI→Gemini conversion
  and sends through that client. A test can therefore replace only the external
  HTTP transport, use a non-expiring fake OAuth credential with a cached fake
  project, and keep every NA2H conversion/route/SSE layer real.
- The two-turn test must not monkeypatch `adapter.forward`, because that would
  bypass exactly the Gemini payload and thought-signature replay contract v0.5
  is meant to prove.
- Existing route tests do patch `adapter.forward`; they prove Responses SSE
  formatting but not the public Responses→Chat→Gemini request or raw AGY
  Gemini→Chat→Responses response chain. The new tracer closes this evidence gap
  rather than duplicating their assertions.
- A raw AGY streaming function-call event can include both a stable
  `functionCall.id` and `thoughtSignature`. The public Responses stream must
  expose the signature as a reasoning carrier and on the tool item so the
  caller can replay both with a matching tool output in turn two.
- Responses history already accepts either a reasoning carrier immediately
  before a call or the tool item's `extra_content`; it reconstructs one Chat
  assistant tool-call message followed by ordered tool outputs. The tracer can
  replay the exact completed public output items without inventing private data.
- AGY stream conversion preserves an explicit `functionCall.id`; using a stable
  fake `call_agent_1` lets the test assert request/result pairing without
  depending on generated UUIDs. Normal function tools avoid custom-tool item-ID
  normalization in the first vertical slice.
- The first implementation mismatch was fixture-side: Responses
  `function_call_output.output` is replayed as textual tool content, while the
  tracer supplied a raw dict that `_content_text` correctly did not treat as a
  content part. A JSON string matches Codex's public tool-result shape and lets
  the real Gemini converter recover the structured response object.
- Final review confirms the only runtime-path change is an injectable
  request-scoped HTTP client factory; routing, scheduling, AGY conversion, and
  SSE code are otherwise unchanged. No live generation smoke is proportionate
  for this fake-transport/CI release because the new gate directly exercises
  the changed factory through both public turns.
- The hosted GitHub workflow cannot run until these changes are pushed. Local
  commands equivalent to every workflow step have passed; release reporting
  must distinguish that from an actual GitHub Actions run.
