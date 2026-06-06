description: Completed review of generated-ingest preflight, Compose readiness, and failure diagnostics
prereq: compose-generated-ingest-checkpoint
files: ai-stream-director/scripts/compose_generated_ingest_checkpoint.py, ai-stream-director/tests/test_compose_generated_ingest_checkpoint.py
----
Reviewed and hardened the opt-in generated-ingest checkpoint.

Review findings fixed:

- Separated the Docker Compose environment from the host-side smoke environment.
  `LOOKBACK_BUFFER_HOST_DIR` is normalized for the bind source and host buffer
  inspection without replacing the container's `LOOKBACK_BUFFER_DIR`.
- Anchored relative host buffer paths to the Compose project directory and
  rejected POSIX-root paths on Windows before they can create unintended
  drive-root directories such as `C:\dev\shm\clutchcam`.
- Confirmed and tested Docker Compose v2 service-state parsing for both JSON
  arrays and JSON-lines output, with malformed non-object records rejected.
- Kept empty health compatible with Compose output, waited on starting or
  unknown non-empty health values, and failed immediately on unhealthy or
  terminal state/status values.
- Clamped each service-state query to the remaining readiness budget so a
  single `docker compose ps` call cannot overrun the configured poll timeout.
- Preserved the primary checkpoint failure when diagnostic commands raise or
  fail, while retaining bounded diagnostic state and log attempts.
- Extended redaction to JSON-style secret assignments, external exception
  text, media summary URLs and commands, and publish output. URL credentials,
  bearer tokens, and secret-named environment values remain redacted.
- Preserved schema version 1 and all previously documented top-level report
  fields while adding the preflight and diagnostics sections.
- Confirmed `--no-compose` skips `compose up` but still performs preflight and
  validates both targeted services before publish.

Validation from `C:\ClutchCam\ai-stream-director`:

```powershell
python -B -m unittest tests.test_compose_generated_ingest_checkpoint tests.test_smoke_entrypoints tests.test_checkpoint_smoke_runner tests.test_linux_compose_stack -v
python -B scripts/compose_generated_ingest_checkpoint.py --indent 0
python -B -m py_compile scripts/compose_generated_ingest_checkpoint.py tests/test_compose_generated_ingest_checkpoint.py
git diff --check -- ai-stream-director/scripts/compose_generated_ingest_checkpoint.py ai-stream-director/tests/test_compose_generated_ingest_checkpoint.py
```

Results:

- 53 focused and integration tests passed.
- Safe default output remained structured, skipped, schema version 1, and
  exited successfully without touching live boundaries.
- Both changed Python files compiled successfully.
- `git diff --check` passed; Git only emitted the repository's existing
  LF/CRLF conversion warnings.
- No real Docker Engine, Compose stack, FFmpeg process, Linux path, or network
  access was required.
