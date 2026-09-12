# NotAccess2Hakimi

OpenAI-compatible Gemini proxy with account pooling and built-in traffic metering.

> Current release: **v0.6.0** — single-account setup, diagnosis, and generic client handoff.

See [CHANGELOG.md](CHANGELOG.md) for release notes.

Current main also supports separate user API keys, persistent request budgets and
grouped remote OpenAI-compatible gateways. See [multi-user deployment](docs/multi-user-deployment.md)
for setup, permissions and the single-worker boundary.

NotAccess2Hakimi aggregates AI Studio API keys and Antigravity OAuth
credentials behind one endpoint. It speaks OpenAI `/v1/chat/completions` and
Codex-compatible `/v1/responses`, with SQLite-backed usage tracking and
tokscale-style token cost estimation.

## Features

- **Account pool**: round-robin/LRU scheduling with 429 cooldown, 401/403
  disable, and automatic failover across credentials and upstreams.
- **Two upstreams**: AI Studio (OpenAI-compatible passthrough, zero conversion)
  and Antigravity Cloud Code (OAuth refresh + Gemini-to-OpenAI conversion).
- **Traffic metering**: real-time token counting and cost estimation per
  credential, model, and day, stored in SQLite. Queryable via `/v1/usage`.
- **Bearer auth**: protect the proxy when exposing on LAN/public.
- **Upstream proxy**: route all upstream traffic (AI Studio + Antigravity
  OAuth) through a SOCKS/HTTP proxy, e.g. `socks5://127.0.0.1:1080`.
- **Browser OAuth**: add an Antigravity account through a local or remote
  Google OAuth callback instead of copying client IDs and refresh tokens by hand.
- **Capability discovery**: `/v1/models` advertises verified context/output
  limits, reasoning levels, modalities, protocols, and provenance for generic
  OpenAI-compatible clients without guessing unknown values.
- **Portable credentials**: preview and restore a versioned credentials-only
  backup over loopback or HTTPS without copying runtime access tokens.
- **Layered health**: one manual account check distinguishes OAuth,
  Antigravity control-plane, and real inference failures without background polling.
- **Reliability gate**: exercise public Responses routing, single-flight leases,
  failover, and error classification against isolated fake upstreams.
- **Agent compatibility gate**: stream a signed tool call through the public
  Responses API, replay its result, and verify the final assistant turn end to end.
- **Operator CLI**: start with `hakimi serve`, inspect local setup with a
  traffic-free `hakimi doctor`, and opt into staged upstream checks with `--live`.
- **Unified verification**: manually compose OAuth, control-plane, quota,
  non-streaming Responses, and a signed two-turn Agent replay into one redacted,
  downloadable structural report with offline replay.
- **Guided first use**: the single-page UI leads from browser OAuth to account
  repair or a generic OpenAI-compatible Base URL/model handoff.

## Quick Start

Hakimi uses `uv` for Python and dependencies; no separate version manager is required.

```bash
# Install Python + dependencies with uv
uv python install 3.11
uv sync --extra dev

# Start with a private config path; Hakimi creates it and prints the initial key
uv run hakimi serve --config config.local.yaml
```

Then open `http://127.0.0.1:12345` in your browser. The Web UI can add
credentials, start Antigravity browser OAuth, run a connection test, and show
runtime pool status; a first-time user does not need to edit OAuth fields or
create the YAML by hand.
`12345` is the repository default; an explicit `port` in `config.local.yaml`
wins. For example, an existing `port: 8000` configuration remains at
`http://127.0.0.1:8000`.

On the first `hakimi serve`, a strong deployment key is generated automatically
when the selected config is missing or has no `auth_token`. It is saved in the
mode-0600 config and printed once in that terminal. Use it for both the Web
login and downstream API clients. Later starts reuse it silently. Treat that
first-start terminal output as sensitive.

For a deliberate rotation, generate a replacement without changing the config:

```bash
uv run hakimi generate-key
```

Save the replacement as `auth_token` in the private config (or enter it in Web
UI Settings), restart NA2H, and use that same value as `OPENAI_API_KEY`. If the
initial generated key cannot be persisted, `hakimi serve` refuses to start
instead of falling back to open access.

### Diagnose setup

The default command checks only the local config and running NA2H instance. It
does not refresh OAuth or call Google:

```bash
uv run hakimi doctor --config config.local.yaml
uv run hakimi doctor --config config.local.yaml --json
```

Run the existing OAuth → control-plane → inference health check only when you
explicitly want real upstream traffic:

```bash
uv run hakimi doctor --config config.local.yaml --live
```

With multiple accounts, select one explicitly, for example
`--credential antigravity:my-account`. Doctor never prints API keys, OAuth
secrets, refresh/access tokens, proxy URLs, or the downstream Bearer token.

For a bounded end-to-end Antigravity check, use `verify`. It performs setup
checks plus exactly three inference requests: one non-streaming response and a
two-turn streamed function-call/result replay. This is explicit operator
traffic and is never triggered by page loads or background polling:

```bash
uv run hakimi verify --config config.local.yaml --output verification.json --json
uv run hakimi verify --replay verification.json --json
```

With multiple Antigravity accounts, add `--credential my-account`. The optional
report file is mode `0600` and contains only an account hash, stage status and
latency, safe error types/statuses, and structural protocol fingerprints. It
does not retain prompts, generated output, call IDs, thought signatures, OAuth
values, project IDs, proxy URLs, or the deployment key. Replay validates the
passing-stage invariants locally and does not contact NA2H or Google.

### Quick smoke test

Use the bearer token configured in `config.local.yaml`:

```bash
export HAKIMI_TOKEN=your-secret-bearer-token

curl -fsS http://127.0.0.1:12345/healthz
curl -fsS http://127.0.0.1:12345/v1/models \
  -H "Authorization: Bearer $HAKIMI_TOKEN"
curl -fsS http://127.0.0.1:12345/v1/responses \
  -H "Authorization: Bearer $HAKIMI_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"model":"antigravity/gemini-3.8-flash","input":"Reply exactly: OK","max_output_tokens":512}'
```

The final response should contain `output_text: "OK"`. If the pool is
rate-limited, wait for cooldown or use another authorized credential; a 503 is
not an authentication success. Tiered reasoning can consume part of the output
budget internally, so very small limits such as 32 may yield no visible text.

## Client Configuration

### Protocol reliability

Usage-recording failures are logged independently of upstream success and cannot
prevent connection cleanup or account lease release. Close failures do not skip
the remaining cleanup operations. Busy providers share one monotonic wait deadline.

Responses distinguishes normal completion from output-limit/content-filter
incompleteness and upstream failure. EOF without a finish reason is a failure;
the proxy does not synthesize a successful stop. Partial tool arguments are not
finalized on incomplete or failed streams, and started streams are not replayed.
Gemini thought signatures remain opaque across tool-call history conversion.

Tool declarations must have unique names across namespaces and additional tools.
Duplicate names return HTTP 400 before contacting upstream instead of silently
dropping a declaration. Full reversible namespace mapping is not implemented yet.

Point any OpenAI-compatible client at the proxy:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:12345/v1
export OPENAI_API_KEY=your-proxy-bearer-token
export CODEX_MODEL=antigravity/gemini-3.8-flash
```

Codex uses the Responses facade. It translates the request to the existing
Chat Completions upstream path and converts text/tool-call results back to
Responses JSON or SSE events. The original `/v1/chat/completions` endpoint
remains available for clients that use that protocol.

When switching between Hakimi and a direct Codex subscription model, start a
new Codex session so provider-specific tool history is not replayed upstream.

Bare model names prefer AI Studio. Use `antigravity/gemini-3.8-flash` or
`antigravity/gemini-3.8-flash-tiered` to explicitly select the Antigravity
route. The adapter resolves the 3.8 display alias to the tiered transport ID;
the equivalent 3.7 aliases remain supported. `gemini-3.6-flash-high` is a
separate catalog model, not an automatic alias for 3.8.

`GET /v1/models` is provider-aware: it exposes the AI Studio catalog only when
an AI Studio credential is configured, the Antigravity catalog only when an
Antigravity credential is configured, and their union when both are configured.
It is a configured-provider catalog rather than a live per-account quota list;
upstream availability and quota can still vary by account.

### v0.6.0 boundary

This release targets a trusted local operator and one Uvicorn worker. Each
credential allows one in-flight request, with a bounded wait and upstream
failover. `/readyz` exposes traffic-free local readiness, and the reliability
gate checks text, failure, and signed Agent tool-loop paths without using stored
credentials or network traffic. v0.6 improves one-account setup and recovery;
it does not expand pool scheduling. Runtime pool state resets on restart.
Virtual keys, per-user quotas, distributed workers, and quota prediction are
deliberately not part of this version.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-compatible chat (stream + non-stream) |
| `/v1/responses` | POST | Codex-compatible Responses (stream + non-stream) |
| `/v1/models` | GET | List models with generic capability metadata |
| `/v1/usage` | GET | Aggregated usage by credential x model x day |
| `/v1/usage/export` | GET | Individual usage log entries |
| `/v1/credentials` | GET | Credential pool status |
| `/healthz` | GET | Health check |
| `/readyz` | GET | Passive readiness; 503 when no credential is locally active |
| `/` | GET | Single-page Web UI |

## Web UI

The built-in single-page console at `/` provides:

- browser-visible `NA2H` product identity, with persisted Simplified Chinese /
  English selection and system / light / dark appearance controls available on
  both the login screen and console
- one state-driven next action for login, credential repair, or client handoff
- service health, active credential counts, total requests/tokens/cost
- AI Studio and Antigravity add/edit/delete cards with live state badges
- manual Antigravity Gemini shared-pool snapshots with 5h and Weekly/7d
  progress bars and upstream reset times
- manual Antigravity full verification with an explicit three-inference warning,
  inline stage result, and client-side redacted-report download
- per-credential and per-model input, cached-input, cache-write, output, and
  reasoning-token breakdown
- a collapsed settings section for host, port, auth token, retry count, cooldown,
  database path, upstream proxy, and diagnostic journal status

The deployment key is both the Web login and downstream API key. It is never
returned by `/api/config` or rendered into the settings form. After login, the
generic configuration button writes the complete configuration—including the
key—to the clipboard only when clicked. Treat that clipboard content as a
secret. Login is session-only by default; **在此浏览器中保持登录** explicitly
opts into persistent browser storage, and **退出** removes both copies.
Language and theme choices are stored separately as non-secret browser
preferences. Changing language redraws static copy and live status, quota,
verification, OAuth, migration, and settings messages; model IDs, provider
names, API fields, and machine-readable error types remain unchanged.

Credential edit forms never echo secrets. Leave a secret field blank to keep the
stored value; enter a new value only when rotating it. The credential list
returns `*_set` metadata instead of secret fragments. `可调度`/`active` means the
credential is locally eligible for selection, not that a remote connection test
has succeeded; use the row-level **检查** action for an OAuth → control-plane →
inference check. It runs only when clicked and does not poll Google in the background.

The Antigravity **刷新额度** action queries Google's grouped quota summary for
that account and caches the last successful Gemini shared-pool snapshot in
memory. The normal UI shows the 5h and Weekly/7d remaining windows rather than
pretending each model has an independent budget. If grouped data is unavailable,
the model catalog is used only as a clearly labelled availability fallback.
Page reloads do not contact Google, a failed refresh does not cool down an
otherwise healthy inference credential, and the snapshot is cleared on process
restart or account rotation. It is an upstream-reported hint, not local
accounting or a promise that the next request will be accepted.

The Antigravity **完整自检** action composes the account's local, OAuth,
control-plane, quota, non-streaming Responses, streamed function-call, and
signed tool-result replay checks. It asks for confirmation because it makes
three inference requests. The action pins one selected account, does not hold a
setup lease while Responses runs, stores no report on the server, and downloads
only the same allowlisted structural report returned by the authenticated API.
Its first streamed turn explicitly selects the fixed `list_files` fixture, so a
live model cannot replace the required tool call with an ordinary text answer;
the second turn remains unconstrained and must produce visible final text.

The usage dashboard is local SQLite metering. **API 等价成本** estimates the
corresponding public API list-price value; it is not an Antigravity charge or
subscription balance. New Antigravity requests preserve cached-input and
reasoning-token details when Google reports them. Older rows cannot be
retroactively split and therefore remain in their previously recorded form.

The **凭证迁移** action exports a sensitive, versioned JSON backup and previews
new/conflicting IDs before restore. It includes long-lived API keys and refresh
tokens, but excludes access tokens, proxy settings, downstream Bearer auth, and
usage data. The endpoint refuses secret transfer over remote plaintext HTTP;
store the downloaded file as carefully as the original config.

If `auth_token` is set, the UI shows a login screen. Otherwise it's open access
and is safe only on loopback during initial setup.

### Reliability behavior

Each credential serves at most one request at a time. If all matching
credentials are busy, a request waits up to 30 seconds and then returns
`capacity_exhausted` (503). Rate limits and transient upstream failures may
fail over to another credential; authentication failures disable that
credential until it is repaired. Terminal upstream 4xx errors fail fast, and
an upstream 2xx response with no usable output is reported as a 502 instead of
silently completing. Streaming requests can fail over only before the first
meaningful output event; after output starts, the proxy emits a normalized SSE
error and does not fabricate `response.completed`.

Runtime fields in `/api/credentials` and `/healthz` show in-flight requests,
health, cooldown, last latency, and the last safe error. These are in-process
signals: run a single Uvicorn worker when relying on them; no distributed
coordination or quota accounting is implied.

`/healthz` is process liveness and remains 200 without credentials. `/readyz`
is a public, traffic-free readiness check: it returns 200 when at least one
credential is locally active and 503 when the pool is empty, disabled, or fully
cooling down. A busy active credential remains ready because requests can wait
inside the existing bounded queue.

### API Endpoints (for Web UI)

| Endpoint | Method | Description |
|---|---|---|
| `/api/config` | GET/PUT | Read/update proxy settings |
| `/api/credentials` | GET | List all credentials with pool status |
| `/api/credentials/aistudio` | POST | Add AI Studio key |
| `/api/credentials/aistudio/{id}` | PUT/DELETE | Partially update/delete; omitted secrets are preserved |
| `/api/credentials/antigravity` | POST | Add Antigravity account |
| `/api/credentials/antigravity/{id}` | PUT/DELETE | Partially update/delete; omitted OAuth fields are preserved |
| `/api/credentials/antigravity/{id}/quota/refresh` | POST | Manually refresh and cache one account's shared-window quota snapshot |
| `/api/credentials/antigravity/{id}/verify` | POST | Run one bounded full verification and return a redacted structural report |
| `/api/credentials/antigravity/oauth/start` | POST | Start local/remote browser OAuth |
| `/api/credentials/antigravity/oauth/status/{state}` | GET | Poll the OAuth login |
| `/api/credentials/antigravity/oauth/complete` | POST | Submit a copied callback URL or one-time OAuth code |
| `/api/credentials/export` | GET | Download a credentials-only backup (HTTPS/loopback only) |
| `/api/credentials/import` | POST | Preview/apply a credential restore (HTTPS/loopback only) |
| `/api/credentials/{kind}/{id}/test` | POST | Check one credential and return stage/latency/error type |
| `/api/usage/summary` | GET | Aggregated detailed token stats and API-equivalent cost |

## Configuration

See [config.example.yaml](config.example.yaml) for the full format.

### AI Studio (API Key mode)

Configure API keys only for projects and accounts you are authorized to use.

### Antigravity (OAuth mode)

The Web UI's **+ Antigravity 登录** button is the recommended path. It opens a
Google consent page and always uses a listener-free PKCE flow with
`https://antigravity.google/oauth-callback`. Complete Google login in any
Google-accessible Chrome; that page then displays **Paste this code into your
application**. Copy that one-time code and paste it into the dialog. Hakimi
validates the session state, sends the PKCE verifier held by the NA2H session to
Google, exchanges the code with the matching Antigravity callback URI, and
stores the account and tokens in the mode-0600 local config. This does not
require `agy`, a local Google login, or a user-supplied OAuth client secret. Manual fields remain a
headless fallback. When `project` is empty, Hakimi discovers it with
`loadCodeAssist`. `onboardUser` changes account state and is disabled unless
that credential explicitly sets `auto_onboard: true`. Cloud Code API endpoints
are tried in fallback order (daily -> prod).

Fresh installations include the shared Antigravity installed-app client pair;
no Antigravity installation or existing account configuration is required.
The client metadata follows [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI/blob/main/internal/auth/antigravity/constants.go).
Hakimi reads the application-level client ID and secret from the local config
when present; environment overrides are also available for deployments using a
different OAuth client. These values are not account credentials and are not
required from the user in the Web UI. If the config already contains one
Antigravity account, Hakimi reuses its client ID and secret for the browser
flow.

Older configs that contain the default client ID but no client secret use the
same bundled pair for login and token refresh. An explicitly configured secret
or a different client ID is preserved; custom public clients keep an empty
secret. Account refresh tokens remain private local data and are never bundled.

Access tokens are refreshed on demand five minutes before expiry, with a
per-account lock to avoid duplicate refreshes. If Google rotates the refresh
token, the new value is persisted locally. This is not an artificial keepalive:
Google can revoke or expire a refresh token, or deny the account upstream; in
those cases the UI reports that browser authorization is required again.

`config.yaml` and `config.local.yaml` are ignored by Git and saved with mode
`0600`; never commit access tokens, refresh tokens, or client secrets. Treat
credentials exposed in chat or obtained from a third party as compromised.

### Server deployment

Keep NA2H bound to loopback and place an HTTPS reverse proxy such as Caddy or
Nginx in front of it. Set a strong `auth_token`, restrict the upstream port with
a firewall, and make the proxy pass the original HTTPS scheme so FastAPI sees
`request.url.scheme == "https"`. Do not expose port `51121`; remote OAuth mode
does not bind it.

The Web UI always uses the listener-free OOB OAuth flow. Credential
import/export is rejected unless the
request is genuine loopback traffic or reaches NA2H as HTTPS. Directly binding
NA2H to `0.0.0.0` over plaintext HTTP is not a supported secret-management
deployment.

The supported `hakimi serve` command provisions a missing deployment key before
starting any listener and fails closed if that key cannot be written. This is a
guardrail, not a replacement for HTTPS, firewall rules, or reverse-proxy
authentication.

### Upstream Proxy

Set `proxy` in the config to explicitly route all upstream requests through a
SOCKS or HTTP proxy. This applies to both AI Studio API calls and Antigravity
OAuth token refresh. Requires `httpx[socks]` (included by default) for SOCKS.

Leave `proxy` empty to use the automatic order at process start:
explicit proxy environment variables, Python/system proxy settings, then Linux
GNOME manual proxy settings. If none is available, Hakimi uses a direct
connection. The Web UI and `/healthz` expose only the selected source
(`config`, `environment`, `system`, or `direct`), never proxy credentials.

## Pricing

Built-in pricing table covers Gemini models (3.8 Flash, 3.7 Flash, 3.5 Flash, 2.5 Pro,
etc.) with per-token rates from the official pricing page. Override with
[pricing.yaml](pricing.example.yaml).

Cost is computed per-request using a five-dimensional token breakdown
(input, output, cache_read, cache_write, reasoning), matching tokscale's model.

## Development

```bash
uv run pytest -v

# Bounded public-API reliability gate; uses only temporary fake credentials,
# fake upstream responses, and temporary SQLite state
uv run python -m hakimi_proxy.reliability_gate

# Stable normal runtime (no implicit file watcher)
uv run hakimi serve --config config.local.yaml

# Legacy module entry remains supported
HAKIMI_CONFIG=config.local.yaml uv run python -m hakimi_proxy.main

# Explicit development reload; config/database changes do not restart it
HAKIMI_CONFIG=config.local.yaml uv run uvicorn hakimi_proxy.main:app \
  --host 127.0.0.1 --port 12345 --reload \
  --reload-exclude config.local.yaml --reload-exclude 'state/*' --reload-exclude '*.db*'
```

The legacy module/Uvicorn entries do not perform first-start key provisioning;
use them only for development with an already secured config or a loopback-only
listener. Normal operation should use `hakimi serve`.

The repository uses `uv` only. Before opening a pull request or publishing a
new release, run `uv run pytest -q`, `uv run python -m compileall -q src tests`,
`uv run python -m hakimi_proxy.reliability_gate`, and `git diff --check`.
The gate defaults to 500 requests at concurrency 8, exits nonzero on an
invariant failure, and emits a JSON verdict. It also performs a complete signed
tool-call/tool-result Responses round trip. It never reads the operator config
or calls Google. For a larger bounded run, pass `--requests` (maximum 10,000)
and `--concurrency` (maximum 64). GitHub Actions runs the same locked-uv tests,
compile, gate, and package build without repository secrets.

## Project Structure

```
src/hakimi_proxy/
  cli.py             # first-start key, serve, doctor, and report verification/replay
  config.py          # YAML config loading + dataclasses
  model_catalog.py   # Shared model IDs + verified discovery metadata
  credential_bundle.py # Versioned credential backup/restore validation
  diagnostics.py     # Private bounded operational JSONL journal
  reliability_gate.py # Bounded fake-upstream public API reliability check
  verification.py    # Manual staged verification + redacted report replay
  oauth.py           # Local/remote browser OAuth callback + token exchange
  auth.py            # Bearer token middleware
  pool.py            # Credential pool state machine + LRU scheduling
  adapters/
    base.py          # Abstract UpstreamAdapter interface
    aistudio.py      # AI Studio OpenAI-compatible passthrough
    antigravity.py   # OAuth refresh + Cloud Code protocol conversion
  metering/
    models.py        # TokenBreakdown + UsageRecord
    pricing.py       # Pricing table + compute_cost
    store.py         # SQLite usage store
  routes/
    chat.py          # POST /v1/chat/completions (failover + metering)
    responses.py     # POST /v1/responses (Codex facade)
    models.py        # GET /v1/models
    usage.py         # GET /v1/usage, /v1/credentials
    admin.py         # Config management API (/api/*)
  web/
    index.html       # Self-contained Web UI dashboard
  main.py            # FastAPI app factory + entry point
```

Operational diagnostics are written to `state/diagnostics.jsonl`, mode `0600`,
with private directories, 2 MiB parts, and four rotated backups. Records contain
only allowlisted route templates, status codes, timings, version, and safe pool
counts. Request bodies, prompts, headers, query strings, OAuth state, tokens,
and credentials are never written.
