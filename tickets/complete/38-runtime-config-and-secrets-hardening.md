description: Completed runtime configuration validation and secret handling
prereq: faster-whisper-compose-profile, linux-cloud-deployment-topology-runbook
files: ai-stream-director/src/config.py, ai-stream-director/src/services/health.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_runtime_healthcheck_entrypoints.py, ai-stream-director/tests/test_smoke_entrypoints.py, ai-stream-director/.env.example, docs/runbooks/local-linux-compose.md, docs/ARCHITECTURE.md
----
Implemented runtime configuration validation and centralized secret redaction
for structured diagnostics.

What changed:

- `get_config()` now parses typed env values with clearer errors before
  returning `AppConfig`.
- Added validation for URL schemes/hosts, embedded credentials, port ranges,
  stream input URLs, positive durations/counts, endpoint paths, and non-empty
  runtime path settings.
- Preserved local dry-run ergonomics: OBS passwords and OpenAI-compatible local
  AI keys remain optional where they are optional today.
- Added `redact_secrets(...)` and applied it to health-result JSON details.
- Redaction covers current and future secret-shaped key/token/password/secret
  fields, common camel-case token names, and sensitive URL query parameters
  without redacting harmless keyframe-style metrics.
- Updated `.env.example` and runbook/architecture docs with validation and
  secret-handling guidance.

Validation:

- `C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B -m unittest tests.test_dry_run_obs tests.test_runtime_healthcheck_entrypoints tests.test_smoke_entrypoints -v`
- Full suite later passed with 226 tests.

Notes:

- Endpoint URLs with embedded credentials now fail validation; secrets should be
  passed through dedicated env vars or secret stores instead.
