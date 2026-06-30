description: Add a shared live transcription source boundary so future speech finalization modes can feed the app without changing switching logic.
prereq: runtime-transcription-event-source
files: ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/README.md, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/tests/test_runtime_event_pipeline.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_runtime_healthcheck_entrypoints.py
difficulty: hard
----
Implemented and reviewed a provider-agnostic live transcript event source boundary while preserving the current chunked transcription behavior as the default.

The implementation adds `TranscriptEventSource` in `services.transcription_runtime`, keeps `Transcriber.transcribe(AudioInputRef)` available for fixed audio references, and wraps the existing `TranscriptionWorker` chunk discovery loop with explicit `start()` and `stop()` lifecycle methods. Both the standalone JSONL worker and the in-process orchestrator now construct live sources through `build_transcription_event_source(...)`.

Configuration now supports `TRANSCRIPTION_SOURCE_MODE`, defaulting to `chunked`. The reserved `vad-utterance` value normalizes successfully but fails at source construction with a clear unsupported-mode error until a later ticket implements that source. Compose, `.env.example`, and the README runtime settings document the default source mode.

## Review findings

- Checked the implementation commit diff `c74633ecc7c06999fa88241bc3d338a45978be5b` before reading the handoff summary, then reviewed the touched runtime, worker, config, Compose, environment, README, and test files.
- Minor finding fixed inline: `LiveTranscriptionSource` caught `AttributeError` around `worker.start()` and `worker.stop()`, which could misclassify an internal lifecycle bug as an old worker interface. The review change now checks method presence before dispatching, so internal `AttributeError`s surface through the startup error path.
- Minor finding fixed inline: the README runtime settings omitted the new `TRANSCRIPTION_SOURCE_MODE` even though `.env.example` and Docker Compose included it. The README now lists the setting and explains that `vad-utterance` is reserved but unsupported for now.
- Added regression coverage proving a source whose `start()` raises `AttributeError` does not fall back to `run_forever()`.
- No major findings were found. The chunked default path remains the shared construction path, JSONL and live queue behavior remain separated at the sink boundary, and unsupported non-default source modes fail clearly rather than silently falling back.
- No tripwires were added; the remaining known gaps, voice activity detection source implementation and automatic fallback behavior, are already scoped to future work rather than conditional concerns in this change.

Validation run:

- `cmd /c "python -m unittest tests.test_runtime_event_pipeline tests.test_transcription_worker_entrypoint tests.test_dry_run_obs tests.test_runtime_healthcheck_entrypoints"` passed: 84 tests.
- `cmd /c "python -m unittest discover -s tests"` passed: 318 tests.
- `git diff --check` reported no whitespace errors, only existing line-ending normalization warnings for touched files.
