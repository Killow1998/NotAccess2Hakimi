# Private multi-user gateway

Run one NA2H worker. The Web console's **Users and remote upstreams** section
creates independent user keys, edits model permissions and limits, disables keys,
and displays per-key metered usage. Disabling a key blocks new requests; it does
not interrupt an already running generation. The administrator key still supports
existing clients, but must never be distributed to other users.

User keys may call `/v1/models`, `/v1/responses`, `/v1/chat/completions` and their
own `/v1/me` usage endpoint. They cannot access configuration, credentials, global
usage, diagnostics or other users' keys. Keys are shown once at creation and stored
as SHA-256 digests. Use HTTPS to create and distribute them.

Limits are per key: concurrent generations, requests per fixed minute, and requests
per UTC day. Admitted generation requests consume a request budget even if the
upstream fails or the payload is rejected; rate-limit rejections consume nothing.
Concurrency is held through the entire stream and released on cancellation.
Daily/minute counters persist across restart. In-flight state is process-local:
multiple workers or replicas are not supported by this limiter.

Token statistics use upstream-reported usage, not token estimates. A request without
reported usage is absent from metered request counts, but still consumes admission
budget. Request quotas are not token or monetary billing limits.

## Multiple remote gateways

Native Antigravity accounts continue to use the existing credential pool. To
aggregate independent Antigravity reverse proxies, add each as a remote upstream
with an HTTPS OpenAI Chat-compatible base URL (including `/v1`), its API key, a
group name, and explicit upstream model IDs. HTTP is accepted only on loopback.
All endpoints in one group must expose the same model IDs; use separate groups
when capabilities differ. Remote endpoints do not inherit guessed capabilities.

For group `team` and upstream model `antigravity/gemini-example`, clients select
`remote/team/antigravity/gemini-example`. The upstream receives the original model
ID. The local `/v1/models` lists these configured models; discovery does not prove
an upstream account can currently generate.

Each endpoint has one in-flight lease, bounded waiting and existing cooldown/error
handling. Started output is never automatically replayed. Endpoint aliases sharing
one underlying Google account do not create additional account quota. Avoid
configuring the gateway to forward to itself or creating cycles between gateways.

## VPS deployment

Use `uv sync --frozen` and a systemd service running as a dedicated unprivileged
user, with `Restart=on-failure`. Run `uv run --no-sync hakimi serve --config
/var/lib/na2h/config.yaml` from the installed repository. Bind NA2H to loopback;
terminate public TLS at a reverse proxy. Do not replace another service already
using port 443: integrate with its existing routing or use a separate listener.

Only publish the inference endpoints. Keep `/api/`, documentation, health details
and the management console behind a separate restricted entry (for example an
SSH tunnel). Retain NA2H bearer authentication behind the proxy. Disable response
buffering for SSE, use a suitable stream read timeout, and trust forwarded headers
only from the local reverse proxy. Never log Authorization headers or request bodies.

The new `<db_path>.access.sqlite3` stores key digests, policies, budgets and per-user
usage. Existing usage tables are unchanged. Back up this file together with the
configuration and existing usage database while the service is stopped. POSIX
permissions are 0600; Windows deployments need a private user directory with suitable
ACLs. A rollback to an older binary must also remove public user access, because
older versions do not understand user keys or enforce these limits.

Before public deployment, verify real upstream connectivity, streamed tool-call
round trips, simultaneous users, revocation, and restart persistence from an EMP
client. Local mock tests are not a substitute for that VPS acceptance test.
