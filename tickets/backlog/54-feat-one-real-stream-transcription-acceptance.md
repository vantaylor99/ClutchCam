description: Validate one real player stream with live transcription after OBS manual scene control works.
prereq: feat-real-obs-manual-scene-control-acceptance
files: docs/runbooks/real-obs-connection.md, docs/runbooks/local-linux-compose.md, ai-stream-director/src/main.py, ai-stream-director/src/transcription_worker.py
difficulty: medium
----
Once real OBS manual scene control is proven, validate a single real player feed
with live transcription enabled. Start with one stream, preferably `player_1`,
so audio extraction, Faster-Whisper, transcript routing, and OBS status can be
observed without four-stream noise.

Recommended sequence:

- Keep AI-driven switching off at first.
- Publish one real RTMP feed into the media server.
- Run the orchestrator with `LIVE_TRANSCRIPTION_ENABLED=true`,
  `TRANSCRIPTION_SOURCE_MODE=chunked`, and transcript text logging enabled only
  for the short validation window.
- Confirm transcript events appear for the correct player stream.
- Repeat with `TRANSCRIPTION_SOURCE_MODE=vad-utterance` only after the chunked
  pass is stable.

Evidence should include app output, transcription mode, stream ID, whether any
speech was detected, whether any scene switched unexpectedly, and any provider
or FFmpeg errors. Do not enable AI-driven scene decisions until the transcript
quality and stream identity are trustworthy.
