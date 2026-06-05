description: Harden runtime configuration validation and secret handling
prereq: faster-whisper-compose-profile, linux-cloud-deployment-topology-runbook
files: ai-stream-director/src/config.py, ai-stream-director/.env.example, ai-stream-director/tests/, docs/runbooks/local-linux-compose.md, docs/ARCHITECTURE.md
----
The service contracts are environment-driven so the same app can run locally,
across Linux hosts, or against cloud GPU endpoints. Before production use, the
runtime should validate configuration consistently and avoid leaking secrets in
logs, health reports, and smoke outputs.

Configuration hardening should preserve current developer dry-run ergonomics:
tests and smoke scripts must still run without Docker, OBS, GPUs, or real
network services. Validation should focus on values that can be checked locally
before long-running workers start.

TODO:

- Add explicit validation helpers for endpoint URLs, ports, stream IDs,
  durations, filesystem path settings, provider modes, and provider-specific
  required values.
- Keep defaults friendly for dry-run development while failing clearly for
  invalid production-facing values.
- Add a secret redaction helper for `GEMMA_API_KEY`, `OBS_PASSWORD`, and future
  key/token/password settings.
- Apply redaction to health/smoke/config details that could otherwise expose
  secrets.
- Add tests for invalid config values and redaction behavior without live
  network, Docker, OBS, or GPU dependencies.
- Update docs and `.env.example` with safe host-local, LAN, and remote/cloud
  patterns.
