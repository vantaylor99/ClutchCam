description: Implement per-stream FFmpeg audio extraction scaffolding
prereq: local-media-server-ingest
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/src/config.py, ai-stream-director/src/services/transcription.py, ai-stream-director/tests/test_transcription_audio_extraction.py
----
Implement the first concrete audio extraction layer behind
`services.transcription` without wiring it into the live terminal MVP yet.

The first pass should model extraction as restartable FFmpeg workers that read
from the same per-stream input URLs used by the lookback buffer and write or
stream normalized audio chunks for a future Faster-Whisper adapter. It should
remain local-Linux friendly while still being testable on Windows without FFmpeg
installed.

Required behavior:

- Add environment-driven audio extraction settings to `config.py`.
- Preserve stable `stream_id` identity from configured stream inputs through
  `AudioInputRef`.
- Define an implementation-neutral extractor boundary in
  `services.transcription`.
- Provide a concrete `FFmpegAudioExtractor` that can build subprocess commands
  but does not start subprocesses on import.
- Support deterministic fixture extraction for tests.
- Include timestamp fields needed for transcript alignment.
- Keep unit tests independent of OBS, Docker, SRS, FFmpeg, Faster-Whisper, and
  network access.

Suggested implementation details:

- Add `AudioExtractionConfig` with input URLs, output directory, sample rate,
  channel count, chunk duration, codec/container, and FFmpeg executable.
- Add `AudioExtractor` protocol plus an extractor session/status dataclass if
  useful.
- Add `FixtureAudioExtractor` for tests that returns predictable
  `AudioInputRef` values.
- Add `FFmpegAudioExtractor.build_ffmpeg_command(stream_id)` tests that assert
  the configured input and output values are used.
- Reject unknown stream IDs and missing input URLs before subprocess launch.
- Document that timestamp/timebase hardening will be expanded by a future
  session registry ticket before cloud/multi-host deployment.

Validation:

- Run the full Python test suite from `ai-stream-director/`.
- If local Docker or FFmpeg validation is unavailable, record the deferral in
  the review ticket.

TODO:
- Extend `config.py` with audio extraction settings.
- Extend `services.transcription` with extractor protocols/configs and fixture
  plus FFmpeg implementations.
- Add focused unit tests for config defaults, command construction, stream ID
  preservation, fixture extraction, and missing input validation.
- Update architecture, roadmap, status, and app README docs.
- Move this ticket to `review/` with validation notes.
