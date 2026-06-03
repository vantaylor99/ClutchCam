description: Plan Faster-Whisper transcription adapter for TranscriptEvent output
prereq: transcription-audio-extraction
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/src/contracts.py, ai-stream-director/src/services/transcription.py, ai-stream-director/src/transcript_router.py, ai-stream-director/tests/
----
The transcription layer now has per-stream audio extraction scaffolding and can
produce `AudioInputRef` values with stream identity, timestamps, duration,
sample rate, and channel metadata. The next step is to design the adapter that
submits those audio references to a Faster-Whisper-compatible API and normalizes
responses into `TranscriptEvent` objects.

The plan should keep the adapter decoupled from physical infrastructure:

- `TRANSCRIPTION_API_URL` selects local Docker, another local Linux host, or a
  cloud VM endpoint.
- The adapter should not know whether Faster-Whisper is local, remote, CPU, or
  GPU-backed.
- Unit tests should use mocked HTTP responses and fixture `AudioInputRef`
  values, not live audio, Docker, FFmpeg, or network calls.

The design should answer:

- What request shape the first adapter sends for file/URI audio references.
- How response segments map to `TranscriptEvent.start_time_seconds` and
  `end_time_seconds`.
- How chunk-relative timestamps are shifted by `AudioInputRef.starts_at_seconds`.
- How partial/final transcript support is represented.
- Which failures are recoverable `TranscriptionError` values.
- How the terminal MVP can keep using `TranscriptRouter` while future runtime
  code feeds it `TranscriptEvent` objects.

Expected output from this plan ticket:

- An implement ticket for the HTTP Faster-Whisper adapter.
- Any smaller follow-up tickets if live streaming/partial transcript semantics
  need separate work.
