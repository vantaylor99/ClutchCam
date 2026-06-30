description: Add a shared live transcription source boundary so future speech finalization modes can feed the app without changing switching logic.
prereq: runtime-transcription-event-source
files: ai-stream-director/src/services/transcription.py, ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/tests/test_transcription_runtime.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/tests/test_runtime_event_pipeline.py, ai-stream-director/tests/test_dry_run_obs.py
difficulty: hard
----
The existing transcription runtime is centered on `Transcriber.transcribe(AudioInputRef)`, which is correct for fixed audio files but is the wrong shape for long-lived provider streams or local voice-activity-detection state. Add a provider-agnostic runtime source boundary that emits normalized `TranscriptEvent` values and can be owned by both the standalone JSONL worker and the in-process orchestrator source.

Design decision: keep `Transcriber` as the request/response adapter for one audio reference, and add a separate event-source protocol for live modes. Do not force streaming providers into fake `AudioInputRef` calls. The first implementation behind this boundary should wrap the current chunk-discovery plus pump path, so behavior remains unchanged until a later ticket selects a different source mode.

The boundary should make source lifecycle explicit:

- A source starts and stops any extractors, provider streams, local voice activity detection state, and worker threads it owns.
- A source emits normalized `TranscriptEvent` values through the existing `TranscriptEventSink` callable, so `LiveTranscriptQueueSink`, `JsonLinesTranscriptSink`, and `RuntimeTranscriptEventHandler` remain usable.
- Source failures should be isolated and reported with enough context for operators. Request/response chunk failures still produce per-audio-reference failure payloads; long-lived source failures should surface as source-level worker errors.
- Partial events are allowed through the boundary, but the existing live queue and runtime event handler continue to reject partial events from switching decisions.
- The current `TranscriptionRuntimePump` remains available for fixed batches and unit tests.

Configuration should introduce a transcription source mode with a conservative default:

- `TRANSCRIPTION_SOURCE_MODE=chunked` keeps the current fixed chunk discovery, optional overlap, and request/response pump behavior.
- Reserve a normalized value such as `vad-utterance` for the local voice activity detection source implemented by the next ticket.
- Invalid values should fail at config load with a clear list of supported modes.
- The builder should fail soft at startup: if an unimplemented or unsupported non-default mode is selected, return a clear operator error rather than silently falling back. Actual automatic fallback behavior belongs in the ticket that implements the fallback source.

The standalone worker and the in-process live source should share the same source construction path. The orchestrator should not branch on chunked versus voice activity detection versus provider streaming; it should only start a source and drain normalized final transcript events from the existing queue.

## Edge cases & interactions

- Startup failure before a source has signaled readiness must still make `LiveTranscriptionSource.start()` fail instead of leaving the orchestrator running without transcripts.
- Shutdown must stop source-owned extractors and long-lived provider connections even when the orchestrator exits through `/quit`, EOF, KeyboardInterrupt, or startup failure cleanup.
- Partial events emitted by future sources must be visible to JSONL diagnostics but must not trigger switching through the live queue.
- The existing per-reference failure summary should remain unchanged for `chunked` mode so current tests and diagnostics keep their meaning.
- Queue backpressure should stay at the sink boundary: final events may be dropped by `LiveTranscriptQueueSink` when the queue is full, while JSONL worker output should keep flushing line by line.
- Source-mode config must not change the request-mode config. `TRANSCRIPTION_REQUEST_MODE=json` versus `openai-compatible` still belongs to the provider adapter used inside a source.
- Imports must remain side-effect free: defining the new source protocol must not start FFmpeg, create threads, import optional voice activity detection packages, or call network endpoints.

## Tests and validation

- Unit tests should cover config parsing and validation for default, `chunked`, `vad-utterance`, aliases if any, and invalid values.
- Unit tests should prove the chunked source wrapper emits the same accepted, rejected, and failure behavior as the current `TranscriptionWorker.run_once()` path.
- Runtime pipeline tests should prove `LiveTranscriptionSource` can start and stop a generic source without knowing whether it is chunked.
- Worker entrypoint tests should prove JSONL transcript and failure payloads are unchanged in default mode.
- Run focused tests for transcription runtime, worker entrypoint, runtime event pipeline, and config parsing; then run the full Python unit suite from `ai-stream-director/`.

TODO:

- Add a source protocol or small abstract base in `services.transcription_runtime` for live transcript event producers.
- Wrap the current `TranscriptionWorker` chunked behavior in that source boundary without changing default runtime behavior.
- Add `TRANSCRIPTION_SOURCE_MODE` parsing, validation, and tests.
- Update `build_worker(...)` and `build_live_transcription_source(...)` so both paths use the same source construction decision.
- Keep `Transcriber.transcribe(AudioInputRef)` intact for one-shot adapters and tests.
