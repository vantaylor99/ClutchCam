description: Completed OpenAI-compatible transcription adapter mode
prereq: faster-whisper-compose-profile, transcription-event-api
files: ai-stream-director/src/config.py, ai-stream-director/src/services/transcription.py, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/.env.example, ai-stream-director/README.md, docs/ARCHITECTURE.md, docs/runbooks/local-linux-compose.md
----
Added an opt-in OpenAI-compatible multipart transcription mode while preserving
the existing JSON-reference adapter as the default.

What changed:

- Added `TRANSCRIPTION_REQUEST_MODE`, `TRANSCRIPTION_ENDPOINT_PATH`,
  `TRANSCRIPTION_MODEL`, `TRANSCRIPTION_LANGUAGE`, and
  `TRANSCRIPTION_RESPONSE_FORMAT`.
- JSON mode still posts extracted audio references to
  `<TRANSCRIPTION_API_URL>/transcribe`.
- `TRANSCRIPTION_REQUEST_MODE=openai-compatible` uploads readable local paths or
  local `file://` URIs to `/v1/audio/transcriptions`.
- Remote or unreadable audio references fail clearly in multipart mode.
- Text-only responses and verbose JSON segment responses normalize into
  `TranscriptEvent` values while preserving stream identity and media-relative
  timestamps.
- Docs and env examples now distinguish JSON-reference services from stock
  OpenAI-compatible Faster-Whisper servers.

Validation:

- `C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B -m unittest tests.test_transcription_event_api tests.test_transcription_audio_extraction tests.test_transcription_worker_entrypoint -v`
- Result: 31 tests passed.

Notes:

- Multipart mode intentionally remains auth-free for the stock local
  Faster-Whisper server path.
- Text-only responses require `AudioInputRef.duration_seconds` so the emitted
  transcript event has bounded timestamps.
