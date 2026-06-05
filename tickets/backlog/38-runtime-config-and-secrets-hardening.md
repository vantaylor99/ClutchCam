description: Harden runtime configuration validation and secret handling
prereq: faster-whisper-compose-profile, linux-cloud-deployment-topology-runbook
files: ai-stream-director/src/config.py, ai-stream-director/.env.example, docs/runbooks/local-linux-compose.md, docs/ARCHITECTURE.md
----
The service contracts are environment-driven so the same app can run locally,
across Linux hosts, or against cloud GPU endpoints. Before production use, the
runtime should validate configuration consistently and avoid leaking secrets in
logs, health reports, and smoke outputs.

Expected behavior:

- Validate endpoint URLs, ports, stream IDs, durations, filesystem paths, and
  provider-specific required values before long-running services start.
- Keep `GEMMA_API_KEY`, OBS password, and future transcription/API credentials
  out of structured logs, smoke reports, and health details.
- Document safe `.env` patterns for host-local, LAN, and remote/cloud endpoints.
- Preserve the current developer dry-run ergonomics.
- Add tests for invalid values and secret redaction without requiring network,
  Docker, OBS, or GPU services.
