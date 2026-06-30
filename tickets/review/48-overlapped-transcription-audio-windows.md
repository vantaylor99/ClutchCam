description: Add an opt-in transcription overlap mode so speech at audio chunk boundaries keeps context without sending duplicate transcript events downstream.
prereq: per-stream-transcript-utterance-assembler
files: ai-stream-director/src/config.py, ai-stream-director/src/services/transcription.py, ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/README.md, docs/ARCHITECTURE.md, ai-stream-director/tests/test_transcription_audio_extraction.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/tests/test_transcription_runtime.py, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/tests/test_linux_compose_stack.py, ai-stream-director/tests/test_runtime_healthcheck_entrypoints.py
difficulty: medium
----
Implemented opt-in transcription request overlap for local WAV audio chunks.

What changed:

- Added `TRANSCRIPTION_REQUEST_OVERLAP_SECONDS` as `AppConfig.transcription_request_overlap_seconds`, defaulting to `0`.
- Config validation rejects negative overlap, overlap greater than or equal to `AUDIO_EXTRACT_CHUNK_SECONDS`, and non-WAV audio extraction containers when overlap is enabled.
- Extended `AudioInputRef` with `emit_from_seconds`, a media-timeline threshold used to suppress transcript events that came entirely from overlap context.
- Added a standard-library `wave` request-window builder that writes composed WAV files under `<AUDIO_EXTRACT_DIR>/_overlap/<stream_id>/<chunk_stem>.wav`.
- Added `OverlappedAudioWindowDiscovery`, which decorates `CompletedAudioChunkDiscovery`, infers the previous numbered chunk when possible, falls back cleanly when previous audio is unavailable, and deletes no-longer-referenced composed files on later discovery passes.
- Updated `build_worker(...)` so disabled overlap keeps plain `CompletedAudioChunkDiscovery`; positive overlap wraps it.
- Updated `TranscriptionRuntimePump` to reject overlap-only events without calling the sink, while preserving boundary-spanning events.
- Updated `FasterWhisperTranscriber` response parsing to reject timestampless text-only responses when `emit_from_seconds` is set, while preserving existing non-overlapped text-only behavior.
- Documented the environment variable in Compose, `.env.example`, README, and architecture docs.

Validation performed:

```powershell
cd ai-stream-director
python -m unittest tests.test_transcription_audio_extraction tests.test_transcription_worker_entrypoint tests.test_transcription_runtime tests.test_transcription_event_api tests.test_linux_compose_stack -v
python -m unittest discover -s tests -v
```

Results:

- Focused suite: 74 tests passed.
- Full suite: 312 tests passed.

Reviewer notes:

- The overlap implementation intentionally uses local WAV composition only; config validation prevents enabling it with any other extraction container.
- Missing, unreadable, invalid, or incompatible previous chunks log a warning and fall back to the original current chunk reference.
- The runtime counts overlap-only drops as rejected events. It does not call the sink for those drops.
- No known test gaps from this implementation pass.
