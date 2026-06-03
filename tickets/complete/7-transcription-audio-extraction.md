description: Completed review of per-stream FFmpeg audio extraction scaffolding
prereq: local-media-server-ingest
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/.env.example, ai-stream-director/src/config.py, ai-stream-director/src/services/transcription.py, ai-stream-director/tests/test_transcription_audio_extraction.py
----
Completed review of the first per-stream audio extraction implementation.

What landed:

- Environment-driven audio extraction settings in `config.py`.
- Per-stream audio input URL fallback from `AUDIO_INPUT_URL_*` to
  `LOOKBACK_INPUT_URL_*` to `<INGEST_API_URL>/<stream_id>`.
- Extended `AudioInputRef` metadata for duration, codec, sample rate, and
  channel count.
- `AudioExtractionConfig`, `AudioExtractionSession`, `AudioExtractor`,
  `FixtureAudioExtractor`, and `FFmpegAudioExtractor` in
  `services.transcription`.
- FFmpeg command construction for normalized audio chunks per stream.
- Explicit validation for unknown stream IDs and missing input URLs before
  subprocess launch.
- Fixture extraction tests that preserve stream identity and timestamps without
  requiring FFmpeg, SRS, Docker, Faster-Whisper, OBS, or network access.
- Documentation and `.env.example` updates for audio extraction settings.

Validation:

- PASS: `python -m unittest tests.test_transcription_audio_extraction -v`
- PASS: `python -m unittest discover -s tests -v`
- Full suite result: 62 tests OK using the bundled Codex Python runtime.

Remaining work:

- Runtime startup wiring for audio extraction workers.
- Faster-Whisper API adapter over `TRANSCRIPTION_API_URL`.
- Timebase/session registry hardening before multi-host or cloud transcription
  deployment.
