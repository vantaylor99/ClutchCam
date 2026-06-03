description: Implement Faster-Whisper HTTP adapter that emits TranscriptEvent objects
prereq: transcription-audio-extraction
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/src/config.py, ai-stream-director/src/contracts.py, ai-stream-director/src/services/transcription.py, ai-stream-director/src/transcript_router.py, ai-stream-director/tests/test_transcription_event_api.py
----
Implement the first HTTP transcription adapter behind `services.transcription`.
It should accept `AudioInputRef` values from the extraction layer, call a
Faster-Whisper-compatible endpoint configured by `TRANSCRIPTION_API_URL`, and
emit normalized `TranscriptEvent` objects.

Required behavior:

- Add transcription client timeout/config defaults to `config.py` if needed.
- Add a `FasterWhisperTranscriber` or similarly named adapter to
  `services.transcription`.
- Keep the adapter infrastructure-neutral: the endpoint may be local Docker,
  another local Linux host, or a cloud VM.
- Support a simple file/URI request shape for extracted audio chunks.
- Normalize common response shapes with segment-level text, start, end, and
  final/partial status.
- Shift segment-relative timestamps by `AudioInputRef.starts_at_seconds`.
- Preserve `stream_id` on every emitted `TranscriptEvent`.
- Raise `TranscriptionError` for request failures, invalid JSON, unexpected
  response shapes, or unusable segment timestamps.
- Add a `TranscriptRouter.add_event(...)` path so future runtime code can feed
  real transcript events without changing the existing terminal input path.
- Keep unit tests mocked and independent of live HTTP services, Docker, FFmpeg,
  OBS, and network access.

Validation:

- Run targeted transcription adapter tests.
- Run the full Python unit suite from `ai-stream-director/`.

TODO:
- Extend config for transcription HTTP timeout if useful.
- Implement the HTTP transcription adapter and response normalization.
- Add mocked HTTP tests for success, timestamp shifting, response-shape
  tolerance, and failure paths.
- Add `TranscriptRouter.add_event(...)` tests.
- Update docs and `.env.example`.
- Move this ticket to `review/` with validation notes.
