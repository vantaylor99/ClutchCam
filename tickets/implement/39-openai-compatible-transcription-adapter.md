description: Add OpenAI-compatible transcription adapter mode
prereq: faster-whisper-compose-profile, transcription-event-api
files: ai-stream-director/src/config.py, ai-stream-director/src/services/transcription.py, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/.env.example, ai-stream-director/README.md, docs/ARCHITECTURE.md, docs/runbooks/local-linux-compose.md
----
The optional `local-transcription` Compose profile uses a stock Faster-Whisper
server that exposes OpenAI-compatible multipart uploads at
`/v1/audio/transcriptions`. The current runtime `FasterWhisperTranscriber`
posts JSON audio references to `<TRANSCRIPTION_API_URL>/transcribe`, so the
stock profile is useful for direct operator checks but not yet directly usable
by the transcription worker.

Expected behavior:

- Preserve the existing JSON `/transcribe` adapter contract as the default.
- Add an opt-in OpenAI-compatible request mode that can upload local extracted
  audio chunks to `/v1/audio/transcriptions`.
- Keep the app-facing endpoint driven by `TRANSCRIPTION_API_URL`.
- Preserve stream identity and media-relative timestamps in emitted
  `TranscriptEvent` objects.
- Support response shapes from OpenAI-compatible Whisper servers without
  requiring live network access in unit tests.
- Document when to use JSON-reference mode versus OpenAI-compatible multipart
  mode.

TODO:

- Add configuration for transcription provider/request mode, endpoint path,
  model, language, and response format as needed.
- Implement multipart upload only for local `file://` audio refs or local paths;
  fail clearly for remote URIs that cannot be uploaded by the worker.
- Normalize text-only and verbose JSON responses into `TranscriptEvent` values,
  using audio ref start/duration when segment timestamps are absent.
- Add mocked tests for request payloads, auth-free upload, text response, verbose
  segment response, bad URI/path, and malformed responses.
- Update docs and env examples without making Docker, GPU, or network calls part
  of the default test suite.
