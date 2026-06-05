description: Completed opt-in Docker Compose generated-ingest checkpoint
prereq: local-checkpoint-smoke-runner
files: ai-stream-director/scripts/compose_generated_ingest_checkpoint.py, ai-stream-director/tests/test_compose_generated_ingest_checkpoint.py, docs/runbooks/local-linux-compose.md
----
The repo now has an opt-in generated-ingest checkpoint for local Linux Compose
validation.

Built:

- Added `scripts/compose_generated_ingest_checkpoint.py`.
- Default invocation is safe and emits a skipped JSON report.
- Live mode requires `--run` or `GENERATED_INGEST_CHECKPOINT_RUN=true`.
- Live mode starts or targets `media-server` and `buffer-worker`, uses the
  existing media-server smoke helper to publish bounded generated FFmpeg RTMP
  streams, polls buffer metadata, and passes only when at least one lookback
  clip is resolvable.
- The structured report includes schema version, checkpoint name, status,
  duration, stream IDs, Compose command/status, publish summary, buffer
  readiness, failure reason, and operator hints.
- Host-side buffer inspection honors `LOOKBACK_BUFFER_HOST_DIR` when
  `LOOKBACK_BUFFER_DIR` is not explicitly set.
- Added mocked tests for safe default behavior, successful orchestration,
  Compose timeout, buffer timeout, CLI JSON output, configured Docker
  executable reporting, host buffer path handling, and import safety.
- Documented the command in the local Linux Compose runbook.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_compose_generated_ingest_checkpoint tests.test_smoke_entrypoints tests.test_checkpoint_smoke_runner -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts\compose_generated_ingest_checkpoint.py --indent 0
```

Result:

- Focused generated-ingest/smoke suite passed.
- The safe default command emitted skipped JSON and exited 0.
