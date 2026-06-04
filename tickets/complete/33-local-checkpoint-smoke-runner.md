description: Completed one-command local checkpoint smoke runner
prereq: local-stack-smoke-entrypoints, sample-media-integration-harness, operator-runbooks
files: ai-stream-director/scripts/checkpoint_smoke_runner.py, ai-stream-director/tests/test_checkpoint_smoke_runner.py, docs/runbooks/local-linux-compose.md
----
A single checkpoint runner now coordinates the existing smoke boundaries and
produces structured operator-friendly JSON.

Built:

- Added `scripts/checkpoint_smoke_runner.py` as an import-safe coordinator for
  media-server, buffer, transcription, AI, and orchestrator smoke boundaries.
- Live checks are skipped by default. Operators can opt in with `--run-all`,
  per-check `--run-*` flags, or matching `CHECKPOINT_SMOKE_RUN_*` variables.
- Checks can be explicitly skipped with `--skip-all`, per-check `--skip-*`
  flags, or matching `CHECKPOINT_SMOKE_SKIP_*` variables.
- The orchestrator dry-run remains enabled by default because it is bounded and
  does not require Docker, OBS, SRS, Ollama, or transcription services.
- The JSON report includes schema version, aggregate status, duration, per-check
  status, command context, selection/skip reason, error reason, and result
  payload.
- Added tests proving the runner is import-safe, respects CLI/env selection,
  reports failures, and returns the expected exit codes.
- Documented the checkpoint runner in the local Linux Compose runbook.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_checkpoint_smoke_runner tests.test_smoke_entrypoints -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts\checkpoint_smoke_runner.py --skip-all --indent 0
```

Result:

- Focused checkpoint/smoke suite: 23 tests passed.
- `--skip-all` emitted valid structured JSON with all checks skipped and exit
  code 0.
