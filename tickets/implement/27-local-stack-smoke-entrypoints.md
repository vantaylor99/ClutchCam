description: Add no-player local Linux stack smoke entrypoints
prereq: local-linux-compose-profiles
files: ai-stream-director/scripts/smoke_media_server.py, ai-stream-director/scripts/smoke_buffer_worker.py, ai-stream-director/scripts/smoke_transcription_api.py, ai-stream-director/scripts/smoke_ai_endpoint.py, ai-stream-director/scripts/smoke_orchestrator_dry_run.py, ai-stream-director/tests/test_smoke_entrypoints.py, ai-stream-director/README.md
----
The local Linux runtime stack needs smoke entrypoints that prove each boundary
can start and respond without requiring real player machines. These entrypoints
should be small, explicit scripts or documented commands that operators and
future CI jobs can run after Compose profile wiring lands.

Smoke coverage should map to the runtime boundaries:

- Media server: start SRS and verify the HTTP summaries endpoint.
- Generated source ingest: publish short FFmpeg `lavfi` video/audio to one or
  more `live/player_*` streams.
- Buffer worker: verify generated RTMP input produces segment metadata and at
  least one resolvable clip under the configured RAM-backed buffer path.
- Transcription API: post a small generated or fixture audio reference to
  `TRANSCRIPTION_API_URL` and fail clearly when the endpoint is unavailable.
- AI endpoint: verify `GEMMA_API_URL` is reachable and, for local Ollama, that
  `GEMMA_MODEL` is available.
- Orchestrator dry run: start the app with `DRY_RUN_OBS=true` and exercise a
  short transcript/manual-command path without OBS.

The scripts should not assume player capture machines, OBS, GPUs, or cloud
credentials. Any external dependency should have a clear timeout, a precise
failure message, and a way to skip or target a remote endpoint through
environment variables.

TODO:

- Add smoke scripts under `ai-stream-director/scripts/` with import-safe helper
  functions and CLI entrypoints.
- Keep generated-source publish commands short-lived and based on FFmpeg
  `lavfi` sources such as `testsrc` and `sine`.
- Check SRS through `http://127.0.0.1:${SRS_HTTP_API_PORT}/api/v1/summaries` by
  default, with host and port overrides.
- Add a buffer smoke that inspects the configured buffer directory and reports
  stream IDs, latest segment metadata, and clip-resolution status.
- Add transcription and AI endpoint smokes with strict request timeouts and
  endpoint/model settings read from the environment.
- Add an orchestrator dry-run smoke that feeds deterministic terminal input and
  exits cleanly.
- Document the Linux smoke sequence in `ai-stream-director/README.md`,
  including startup, smoke, shutdown, and expected outputs.
- Add tests that mock subprocess and HTTP calls, proving command construction,
  timeout handling, env overrides, and nonzero exit codes on failed checks.
- Run focused tests with bytecode disabled:
  `python -B -m unittest tests.test_smoke_entrypoints -v`.
