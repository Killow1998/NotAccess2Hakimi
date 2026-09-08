# 0.6.1 verification

- Windows native PowerShell 7.6.5: 260 pytest cases passed.
- Reliability gate: 500/500 requests at client concurrency 8; no leaked leases;
  tool-call round trip and simulated 429 failover, upstream 503 and timeout passed.
  This is not a real Antigravity capacity benchmark.
- Ablation: removing model cooldown admission causes the isolation regression to
  fail. Keep this check so limited models wait while other models remain available.
- Removed duplicate expiry pruning on cooldown writes; acquisition handles cleanup.
  Reused the existing OAuth client ID constant instead of duplicating its value.
- Pool and journal responsibilities stay in the existing modules. No extra scheduler
  or tracing framework was introduced.
- CI tests Windows, Linux and macOS.
