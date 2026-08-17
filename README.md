# NotAccess2Hakimi

OpenAI-compatible Gemini proxy with account pool and built-in traffic metering.

Aggregates AI Studio API Keys (single-account multi-Project key pool) and
Antigravity OAuth credentials into a unified endpoint that speaks the OpenAI
`/v1/chat/completions` API. Includes tokscale-style per-token cost computation
and SQLite-backed usage tracking.

## Features

- **Account pool**: round-robin/LRU scheduling with 429 cooldown, 401/403
  disable, and automatic failover across credentials and upstreams.
- **Two upstreams**: AI Studio (OpenAI-compatible passthrough, zero conversion)
  and Antigravity Cloud Code (OAuth refresh + Gemini-to-OpenAI conversion).
- **Traffic metering**: real-time token counting and cost estimation per
  credential, model, and day, stored in SQLite. Queryable via `/v1/usage`.
- **Bearer auth**: protect the proxy when exposing on LAN/public.

## Quick Start

```bash
# 1. Install mise + uv (one-time)
winget install jdx.mise
mise install  # reads .mise.toml, installs uv

# 2. Install Python + dependencies
uv python install 3.12
uv sync --extra dev


# 3. Run
uv run uvicorn hakimi_proxy.main:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000` in your browser to configure credentials and
settings via the Web UI. No YAML editing required.

## Client Configuration

Point any OpenAI-compatible client at the proxy:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8000/v1
export OPENAI_API_KEY=your-proxy-bearer-token
export CODEX_MODEL=gemini-3.7-flash
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-compatible chat (stream + non-stream) |
| `/v1/models` | GET | List available models |
| `/v1/usage` | GET | Aggregated usage by credential x model x day |
| `/v1/usage/export` | GET | Individual usage log entries |
| `/v1/credentials` | GET | Credential pool status |
| `/healthz` | GET | Health check |
| `/` | GET | Web UI dashboard |

## Web UI

The built-in dashboard at `/` provides:

- **Dashboard**: pool status, active credential count, total requests/tokens/cost
- **Credentials**: add/edit/delete AI Studio keys and Antigravity OAuth accounts
  with live state badges (active/cooldown/disabled)
- **Usage**: per-credential and per-model cost breakdown
- **Settings**: host, port, auth token, retry count, cooldown, DB path

If `auth_token` is set, the UI shows a login screen. Otherwise it's open access.

### API Endpoints (for Web UI)

| Endpoint | Method | Description |
|---|---|---|
| `/api/config` | GET/PUT | Read/update proxy settings |
| `/api/credentials` | GET | List all credentials with pool status |
| `/api/credentials/aistudio` | POST | Add AI Studio key |
| `/api/credentials/aistudio/{id}` | PUT/DELETE | Update/delete |
| `/api/credentials/antigravity` | POST | Add Antigravity account |
| `/api/credentials/antigravity/{id}` | PUT/DELETE | Update/delete |
| `/api/usage/summary` | GET | Aggregated usage stats |

## Configuration

See [config.example.yaml](config.example.yaml) for the full format.

### AI Studio (API Key mode)

One Google account can create multiple GCP Projects, each with its own API Key.
Rate limits are per-Project, so N Projects = N x free-tier capacity.

### Antigravity (OAuth mode)

Requires a one-time browser OAuth flow to obtain `refresh_token`. After that,
`access_token` is auto-refreshed silently. Cloud Code API endpoints are tried
in fallback order (daily -> prod).

## Pricing

Built-in pricing table covers Gemini models (3.7 Flash, 3.5 Flash, 2.5 Pro,
etc.) with per-token rates from the official pricing page. Override with
[pricing.yaml](pricing.example.yaml).

Cost is computed per-request using a five-dimensional token breakdown
(input, output, cache_read, cache_write, reasoning), matching tokscale's model.

## Development

```bash
uv run pytest -v          # run tests
uv run uvicorn hakimi_proxy.main:app --reload  # dev server
```

## Project Structure

```
src/hakimi_proxy/
  config.py          # YAML config loading + dataclasses
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
    models.py        # GET /v1/models
    usage.py         # GET /v1/usage, /v1/credentials
    admin.py         # Config management API (/api/*)
  web/
    index.html       # Self-contained Web UI dashboard
  main.py            # FastAPI app factory + entry point
```
