# 0.6.1 verification

- Windows native PowerShell 7.6.5, Python 3.11.14: 266 pytest cases passed.
- Startup logging is verified without `os.fchmod`, which is unavailable on
  Windows before Python 3.13. The regression fails without the capability check.
- Reliability gate: 500/500 requests at client concurrency 8; no leaked leases;
  tool-call round trip and simulated 429 failover, upstream 503 and timeout passed.
  This is not a real Antigravity capacity benchmark.
- Ablation: removing model cooldown admission causes the isolation regression to
  fail. Keep this check so limited models wait while other models remain available.
- Removed duplicate expiry pruning on cooldown writes; acquisition handles cleanup.
  Reused the existing OAuth client ID constant instead of duplicating its value.
- Pool and journal responsibilities stay in the existing modules. No extra scheduler
  or tracing framework was introduced.
- Login and token refresh share default-client completion. A missing-secret
  refresh regression fails without this completion; explicit custom secrets and
  secretless custom clients retain their original behavior.
- Linux live acceptance: the OAuth check, control plane and Gemini 3.8 Flash
  inference succeeded. Two simultaneous Gemini 3.7/3.8 Flash Responses streams
  returned HTTP 200, nonempty text and `response.completed`; request IDs were
  present, observed in-flight requests reached 2 and returned to 0.
  The short prompts used a 256-token output allowance because a reasoning model
  can exhaust a 32-token allowance before returning text. This smoke check does
  not establish sustained upstream capacity or a long-term failure rate.
- The deployed update preserved existing account IDs and the API key; the
  previous working changes, environment and configuration were backed up.
- The wheel includes the Web UI and the tested source; the source distribution
  retains package initializers while excluding local caches and runtime state.
- CI tests Windows, Linux and macOS.
