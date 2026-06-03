description: Review per-stream FFmpeg audio extraction scaffolding
prereq: local-media-server-ingest
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/.env.example, ai-stream-director/src/config.py, ai-stream-director/src/services/transcription.py, ai-stream-director/tests/test_transcription_audio_extraction.py
----
Implemented the first concrete audio extraction layer behind
`services.transcription` without wiring it into the terminal MVP runtime.

Implemented behavior:

- `config.py` exposes audio extraction defaults:
  - `AUDIO_EXTRACT_DIR`
  - `AUDIO_EXTRACT_SAMPLE_RATE`
  - `AUDIO_EXTRACT_CHANNELS`
  - `AUDIO_EXTRACT_CHUNK_SECONDS`
  - `AUDIO_EXTRACT_CODEC`
  - `AUDIO_EXTRACT_CONTAINER`
  - per-stream `AUDIO_INPUT_URL_PLAYER_1` through `AUDIO_INPUT_URL_PLAYER_4`
- Audio input URLs fall back to `LOOKBACK_INPUT_URL_*` and then
  `<INGEST_API_URL>/<stream_id>`, preserving stream identity across ingest,
  buffer, and transcription boundaries.
- `AudioInputRef` now includes duration, sample rate, and channel metadata for
  future Faster-Whisper alignment.
- `AudioExtractionConfig`, `AudioExtractionSession`, `AudioExtractor`,
  `FixtureAudioExtractor`, and `FFmpegAudioExtractor` were added to
  `services.transcription`.
- `FFmpegAudioExtractor` builds one normalized-audio FFmpeg segment command per
  stream, validates unknown stream IDs and missing input URLs before subprocess
  launch, and starts/stops workers only through explicit lifecycle methods.
- Fixture extraction provides deterministic `AudioInputRef` objects for unit
  tests without FFmpeg, SRS, Docker, Faster-Whisper, OBS, or network access.
- Docs and `.env.example` describe the audio extraction settings and current
  limitation that Faster-Whisper wiring is still future work.

Validation:

- PASS: `python -m unittest tests.test_transcription_audio_extraction -v`
- PASS: `python -m unittest discover -s tests -v`
- Full suite result: 62 tests OK using the bundled Codex Python runtime.

Review focus:

- Confirm `AudioExtractionConfig` stays implementation-neutral enough for local
  Linux, multi-local-server, and future cloud transcription topologies.
- Confirm FFmpeg command construction is suitable for SRS RTMP/SRT inputs and
  normalized speech-to-text audio chunks.
- Confirm the URL fallback order is correct for hybrid media/buffer deployments.
- Confirm docs remain clear that extraction is implemented but not yet wired to
  Faster-Whisper or the live terminal MVP.
