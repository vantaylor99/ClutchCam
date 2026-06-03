description: Completed Faster-Whisper HTTP adapter that emits TranscriptEvent objects
prereq: transcription-audio-extraction
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/.env.example, ai-stream-director/src/config.py, ai-stream-director/src/contracts.py, ai-stream-director/src/services/transcription.py, ai-stream-director/src/transcript_router.py, ai-stream-director/tests/test_transcription_event_api.py
----
The first HTTP transcription adapter is complete behind
`services.transcription`.

Built:

- Added `TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS` to `AppConfig` and
  `.env.example`.
- Added `FasterWhisperTranscriber`, which posts `AudioInputRef` metadata to
  `<TRANSCRIPTION_API_URL>/transcribe` and keeps `requests` as a lazy runtime
  dependency.
- Normalized common Faster-Whisper-like response shapes into `TranscriptEvent`
  objects, including top-level single text responses, raw segment lists,
  `segments` lists, `start`/`end`, `start_seconds`/`end_seconds`, `is_final`,
  and `final`.
- Shifted chunk-relative timestamps by `AudioInputRef.starts_at_seconds` and
  preserved the source `stream_id`.
- Raised `TranscriptionError` for request/HTTP failures, invalid JSON,
  malformed response shapes, blank transcript text, and unusable timestamps.
- Added `TranscriptRouter.add_event(...)` so future runtime code can feed real
  transcript events without changing the terminal input path.
- Preserved transcript event timestamps on `TranscriptMessage.timestamp` while
  using receipt time for router history retention, preventing media-time events
  from being immediately pruned by wall-clock cleanup.
- Updated docs to distinguish implemented adapter code from still-pending
  runtime wiring.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_transcription_event_api -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
git diff --check
```

Result:

- Targeted transcription adapter tests: 10 passed.
- Full Python unit suite: 72 passed.
- `git diff --check`: passed; only CRLF conversion warnings were reported.

Usage notes:

- Instantiate with `FasterWhisperTranscriber.from_app_config(get_config())` or
  pass an explicit API URL and timeout.
- The adapter expects extracted audio references such as `file://...wav` or
  another URI understood by the downstream Faster-Whisper service.
- Runtime startup/wiring of FFmpeg audio extraction and transcription workers
  remains future work.
