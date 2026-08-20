# NotAccess2Hakimi

OpenAI-compatible Gemini proxy with account pooling and built-in traffic metering.

> Current release: **v0.1.1** — Responses custom-tool compatibility patch.

See [CHANGELOG.md](CHANGELOG.md) for release notes.

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

## Quick Start

Hakimi uses `uv` for Python and dependencies; no separate version manager is required.

```bash
# Install Python + dependencies with uv
uv python install 3.11
uv sync --extra dev

# Create a private local config, then fill in credentials you control
install -m 600 config.example.yaml config.local.yaml

# Run with that config
HAKIMI_CONFIG=config.local.yaml uv run python -m hakimi_proxy.main
```

Then open `http://127.0.0.1:12345` in your browser. The Web UI can add
credentials, start Antigravity browser OAuth, run a connection test, and show
runtime pool status; no YAML editing is required after the initial local copy.

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
  --data '{"model":"antigravity/gemini-3.7-flash-tiered","input":"Reply exactly: OK","max_output_tokens":32}'
```

The final response should contain `output_text: "OK"`. If the pool is
rate-limited, wait for cooldown or use another authorized credential; a 503 is
not an authentication success.

## Client Configuration

Point any OpenAI-compatible client at the proxy:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:12345/v1
export OPENAI_API_KEY=your-proxy-bearer-token
export CODEX_MODEL=gemini-3.7-flash-tiered
```

Codex uses the Responses facade. It translates the request to the existing
Chat Completions upstream path and converts text/tool-call results back to
Responses JSON or SSE events. The original `/v1/chat/completions` endpoint
remains available for clients that use that protocol.

When switching between Hakimi and a direct Codex subscription model, start a
new Codex session so provider-specific tool history is not replayed upstream.

Bare model names prefer AI Studio. Use `antigravity/gemini-3.7-flash-tiered` to
explicitly select the Antigravity catalog ID. The adapter accepts the display
alias `antigravity/gemini-3.7-flash` and forwards it as
`gemini-3.7-flash-tiered`; `gemini-3.6-flash-high` is a separate catalog model,
not an automatic alias for 3.7.

### v0.1.0 boundary

This release targets a trusted local operator and one Uvicorn worker. Each
credential allows one in-flight request, with a bounded wait and upstream
failover. Runtime state resets on restart. Virtual keys, per-user quotas,
distributed workers, and quota prediction are deliberately not part of this
version.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-compatible chat (stream + non-stream) |
| `/v1/responses` | POST | Codex-compatible Responses (stream + non-stream) |
| `/v1/models` | GET | List available models |
| `/v1/usage` | GET | Aggregated usage by credential x model x day |
| `/v1/usage/export` | GET | Individual usage log entries |
| `/v1/credentials` | GET | Credential pool status |
| `/healthz` | GET | Health check |
| `/` | GET | Single-page Web UI |

## Web UI

The built-in single-page console at `/` provides:

- service health, active credential counts, total requests/tokens/cost
- AI Studio and Antigravity add/edit/delete cards with live state badges
- per-credential and per-model usage breakdown
- a collapsed settings section for host, port, auth token, retry count, cooldown,
  database path, and upstream proxy

Credential edit forms never echo secrets. Leave a secret field blank to keep the
stored value; enter a new value only when rotating it. The credential list
returns `*_set` metadata instead of secret fragments. `可调度`/`active` means the
credential is locally eligible for selection, not that a remote connection test
has succeeded; use the row-level **Test** action for that check.

If `auth_token` is set, the UI shows a login screen. Otherwise it's open access.

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

### API Endpoints (for Web UI)

| Endpoint | Method | Description |
|---|---|---|
| `/api/config` | GET/PUT | Read/update proxy settings |
| `/api/credentials` | GET | List all credentials with pool status |
| `/api/credentials/aistudio` | POST | Add AI Studio key |
| `/api/credentials/aistudio/{id}` | PUT/DELETE | Partially update/delete; omitted secrets are preserved |
| `/api/credentials/antigravity` | POST | Add Antigravity account |
| `/api/credentials/antigravity/{id}` | PUT/DELETE | Partially update/delete; omitted OAuth fields are preserved |
| `/api/credentials/antigravity/oauth/start` | POST | Start local/remote browser OAuth |
| `/api/credentials/antigravity/oauth/status/{state}` | GET | Poll the OAuth login |
| `/api/credentials/antigravity/oauth/complete` | POST | Submit a copied callback URL or one-time OAuth code |
| `/api/credentials/{kind}/{id}/test` | POST | Test one exact credential and return latency/error type |
| `/api/usage/summary` | GET | Aggregated usage stats |

## Configuration

See [config.example.yaml](config.example.yaml) for the full format.

### AI Studio (API Key mode)

Configure API keys only for projects and accounts you are authorized to use.

### Antigravity (OAuth mode)

The Web UI's **+ Antigravity 登录** button is the recommended path. It opens a
Google consent page and listens on the local callback port `51121`; on a remote
server, copy the authorization URL to any Chrome, then paste the complete
`localhost/.../oauth-callback?code=...&state=...` URL (or the one-time code) back
into the dialog. Hakimi validates the session state, exchanges the code, and
stores the account and tokens in the mode-0600 local config. Refresh tokens are
never entered into the remote form. Manual fields remain available as a
fallback for headless setups. When `project` is empty, Hakimi discovers it with
`loadCodeAssist`. `onboardUser` changes account state and is disabled unless
that credential explicitly sets `auto_onboard: true`. Cloud Code API endpoints
are tried in fallback order (daily -> prod).

The OAuth app client secret is an application-level setting, not an account
refresh token. If the config already contains one Antigravity account, Hakimi
reuses that client configuration for the browser flow. On a clean install, set
`HAKIMI_ANTIGRAVITY_CLIENT_SECRET` once or use the manual form for the first
account; later accounts need only browser authorization.

Access tokens are refreshed on demand five minutes before expiry, with a
per-account lock to avoid duplicate refreshes. If Google rotates the refresh
token, the new value is persisted locally. This is not an artificial keepalive:
Google can revoke or expire a refresh token, or deny the account upstream; in
those cases the UI reports that browser authorization is required again.

`config.yaml` and `config.local.yaml` are ignored by Git and saved with mode
`0600`; never commit access tokens, refresh tokens, or client secrets. Treat
credentials exposed in chat or obtained from a third party as compromised.

### Upstream Proxy

Set `proxy` in the config to explicitly route all upstream requests through a
SOCKS or HTTP proxy. This applies to both AI Studio API calls and Antigravity
OAuth token refresh. Requires `httpx[socks]` (included by default) for SOCKS.

Leave `proxy` empty to use the EMP-compatible automatic order at process start:
explicit proxy environment variables, Python/system proxy settings, then Linux
GNOME manual proxy settings. If none is available, Hakimi uses a direct
connection. The Web UI and `/healthz` expose only the selected source
(`config`, `environment`, `system`, or `direct`), never proxy credentials.

## Pricing

Built-in pricing table covers Gemini models (3.7 Flash, 3.5 Flash, 2.5 Pro,
etc.) with per-token rates from the official pricing page. Override with
[pricing.yaml](pricing.example.yaml).

Cost is computed per-request using a five-dimensional token breakdown
(input, output, cache_read, cache_write, reasoning), matching tokscale's model.

## Development

```bash
uv run pytest -v          # run tests
uv run python -m hakimi_proxy.main  # dev server (auto-reload enabled)
```

The repository uses `uv` only. Before opening a pull request or publishing a
new release, run `uv run pytest -q`, `uv run python -m compileall -q src tests`,
and `git diff --check`.

## Project Structure

```
src/hakimi_proxy/
  config.py          # YAML config loading + dataclasses
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
