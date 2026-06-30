description: Add a shared live transcription source boundary so future speech finalization modes can feed the app without changing switching logic.
prereq: runtime-transcription-event-source
files: ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/tests/test_runtime_event_pipeline.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_runtime_healthcheck_entrypoints.py
difficulty: hard
----
Implemented a provider-agnostic live transcript event source boundary while preserving the current chunked transcription behavior as the default.

What changed:

- Added `TranscriptEventSource` in `services.transcription_runtime` with explicit `start()` and `stop()` lifecycle methods.
- Kept `TranscriptionRuntimePump` and `Transcriber.transcribe(AudioInputRef)` intact for fixed audio references and unit tests.
- Made `TranscriptionWorker` implement the chunked source lifecycle by adding `start()` and `stop()` wrappers around its existing `run_forever()` and `stop_event` behavior.
- Added `build_transcription_event_source(...)` so the standalone JSONL worker and the in-process orchestrator live source use the same source-mode construction path.
- Updated `build_worker(...)` to delegate to the shared source builder and remain chunked-worker compatible.
- Updated `LiveTranscriptionSource` to depend on a generic transcript event source instead of branching on chunked worker internals.
- Added `TRANSCRIPTION_SOURCE_MODE` parsing with default `chunked`, accepted aliases for `chunked`, reserved `vad-utterance`, and clear validation for invalid values.
- The source builder fails soft for the reserved but unimplemented `vad-utterance` mode with an operator-facing `TranscriptionError` instead of silently falling back.
- Threaded `TRANSCRIPTION_SOURCE_MODE=chunked` through Docker Compose and `.env.example`.

Behavioral notes for review:

- Default mode remains the existing fixed chunk discovery plus optional overlap plus request/response pump path.
- JSONL transcript payloads and per-audio-reference failure payloads remain unchanged in chunked mode.
- Partial transcript events still pass through JSONL sinks, while `LiveTranscriptQueueSink` and `RuntimeTranscriptEventHandler` continue to reject partial events from switching decisions.
- Startup and shutdown behavior still relies on the chunked source setting the `started_event` after extractor start and stopping owned extraction in `finally`.
- Non-default `vad-utterance` is config-valid but builder-unsupported until the next ticket implements it.

Validation run:

- `cmd /c "python -m unittest tests.test_transcription_runtime tests.test_transcription_worker_entrypoint tests.test_runtime_event_pipeline tests.test_dry_run_obs"` passed: 81 tests.
- `cmd /c "python -m unittest discover -s tests"` passed: 317 tests.

Known gaps:

- No voice activity detection source is implemented here; `vad-utterance` intentionally returns a clear unsupported-mode error from the shared source builder.
- No automatic fallback behavior is implemented; that belongs with the future fallback-source ticket.
