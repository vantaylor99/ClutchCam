description: Completed live transcription event source wiring
prereq: transcription-ffmpeg-supervision
files: ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/tests/test_runtime_event_pipeline.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_runtime_healthcheck_entrypoints.py
----
The orchestrator now has an opt-in, in-process live transcription source that
feeds final `TranscriptEvent` values into the existing
`RuntimeTranscriptEventHandler`. This connects supervised audio extraction and
transcription output to the same router, prefilter, AI director, scheduler, and
switch-target construction path used by normalized runtime transcript events.

Key behavior:

- `LIVE_TRANSCRIPTION_ENABLED` defaults to `false`, preserving typed terminal
  transcript input as the default runtime mode.
- `LIVE_TRANSCRIPTION_QUEUE_SIZE` defaults to `16` and is validated as a
  positive integer.
- `LiveTranscriptQueueSink` queues final transcript events, ignores partial
  events, and drops the newest final event with an operator log message when
  the queue is full.
- `LiveTranscriptionSource` starts `TranscriptionWorker` on a background thread
  with a startup handshake so extractor startup failures surface to `main()`.
- The orchestrator loop drains queued live events on the main thread, preserving
  terminal commands, scheduler ticks, and clean shutdown on `/quit`, EOF, or
  KeyboardInterrupt.
- The standalone `python -m transcription_worker` JSONL path remains the
  default worker behavior; custom sinks are injectable for the in-process
  orchestrator path.

Validation:

- `python -m unittest tests.test_runtime_event_pipeline tests.test_transcription_worker_entrypoint tests.test_dry_run_obs -v`
  - `56` tests passed.
- `python -m unittest discover -s tests -v`
  - `270` tests passed.
- `python -m py_compile src/main.py src/config.py src/transcription_worker.py tests/test_runtime_event_pipeline.py tests/test_transcription_worker_entrypoint.py tests/test_dry_run_obs.py`
  - passed.
- `git diff --check`
  - passed with line-ending normalization warnings only.
