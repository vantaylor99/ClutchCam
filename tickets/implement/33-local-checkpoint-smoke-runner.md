description: Add one-command local checkpoint smoke runner
prereq: local-stack-smoke-entrypoints, sample-media-integration-harness, operator-runbooks
files: ai-stream-director/scripts/, ai-stream-director/tests/test_checkpoint_smoke_runner.py, ai-stream-director/README.md, docs/runbooks/local-linux-compose.md
----
The repo has individual smoke entrypoints for media-server, buffer worker,
transcription API, AI endpoint, and orchestrator dry-run. The next testing
checkpoint needs a single bounded runner that can execute the relevant smoke
checks, collect their outputs, and produce a clear pass/fail report for local
development and Linux host validation.

Expected behavior:
- Add an import-safe checkpoint runner under `ai-stream-director/scripts/`.
- Let operators choose which boundaries to run or skip through CLI flags and
  environment variables.
- Reuse the existing `smoke_*.py` modules instead of duplicating Docker, FFmpeg,
  HTTP, or orchestrator logic.
- Return structured JSON with per-boundary status, duration, command/context,
  and failure reason.
- Default to a no-real-services mode where possible, and keep Docker/FFmpeg/live
  network checks opt-in or explicitly bounded.
- Include tests that mock each smoke boundary; unit tests must not require
  Docker, FFmpeg, SRS, OBS, Ollama, Faster-Whisper, GPUs, or network access.
- Document the runner in the local Linux runbook.

TODO:

- Add a checkpoint runner script under `ai-stream-director/scripts/`.
- Define the JSON report shape for skipped, passed, and failed boundaries.
- Wire the runner to existing smoke modules through injectable callables so
  tests can mock each boundary.
- Add CLI flags or environment knobs for skipping media-server, buffer,
  transcription, AI, and orchestrator checks.
- Add unit tests in `tests/test_checkpoint_smoke_runner.py`.
- Document the runner command and expected output in the local Linux runbook.
- Run:
  `python -B -m unittest tests.test_checkpoint_smoke_runner tests.test_smoke_entrypoints -v`.
