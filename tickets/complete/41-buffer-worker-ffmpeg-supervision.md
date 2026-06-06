description: Completed review of per-stream FFmpeg supervision for the rolling buffer worker
prereq: buffer-worker-runtime-entrypoint
files: ai-stream-director/src/services/buffer.py, ai-stream-director/tests/test_buffer_supervision.py
----
`FFmpegRollingLookbackBuffer` now maintains one independent supervisor thread
per configured stream while preserving the existing `start()` / `stop()` API
used by the buffer worker entrypoint. Each supervisor launches, polls, reaps,
and restarts only its own FFmpeg child, with an independent consecutive-failure
counter and interruptible exponential backoff from 1 second to a 30-second cap.

Review corrections:

- Serialized lifecycle operations so concurrent `start()` / `stop()` calls
  cannot clear an unstarted supervisor and later create duplicate workers.
- Restored repeated `start()` as a true idempotent no-op before filesystem
  setup or runtime validation.
- Measured stable child runtime after a successful process launch so slow
  `Popen` calls cannot incorrectly reset failure backoff.
- Kept child termination outside the process-map lock and retained the
  terminate, bounded wait, kill, bounded wait cleanup sequence.
- Made poll, terminate, wait, and kill cleanup errors non-fatal to shutdown and
  redacted configured input URLs from those diagnostics.
- Included PID directly in child-exit recovery logs and redacted longer
  configured URLs first to avoid prefix leakage.
- Removed a fragile upper timing assertion while retaining lower-bound checks
  that prove restart throttling occurs.

Coverage includes post-start child exit, launch recovery, capped backoff,
independent streams, stable-runtime reset, launch-latency accounting,
idempotent start, concurrent lifecycle serialization, active-child kill
fallback, process-error URL redaction, and interruption of a pending
five-second recovery delay.

Validation:

- `python -B -m unittest tests.test_buffer_supervision -v`: 10 tests passed.
- Supervision suite repeated 20 consecutive times: 200 test executions passed.
- `python -B -m unittest tests.test_rolling_buffer
  tests.test_buffer_worker_entrypoint -q`: 21 tests passed.
- `python -B -m unittest discover -s tests -v`: 247 tests passed.
- `python -m compileall -q src tests`: passed.
- `git diff --check -- ai-stream-director/src/services/buffer.py
  ai-stream-director/tests/test_buffer_supervision.py
  tickets/complete/41-buffer-worker-ffmpeg-supervision.md`: passed.

CodeRabbit CLI review was unavailable on this Windows host: the official
installer reported `Unsupported operating system: mingw64_nt-10.0-26200`, and
WSL is not installed. The repository review and validation above were
completed directly.
