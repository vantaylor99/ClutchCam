description: Plan per-stream audio extraction for real-time transcription
prereq: local-media-server-ingest
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/src/config.py, ai-stream-director/src/contracts.py, ai-stream-director/src/services/transcription.py, ai-stream-director/src/services/ingestion.py, ai-stream-director/src/services/buffer.py, ai-stream-director/tests/
----
The transcription path needs a concrete audio extraction design before the
Faster-Whisper adapter is implemented. The system now has local SRS ingest,
stable stream IDs, FFmpeg lookback buffer workers, and a lightweight
`services.transcription` boundary. The next design step is to define how each
stream's audio is extracted, timestamped, restarted, and handed to the
transcription adapter without blocking video buffering.

The plan should keep the deployment targets explicit:

- Single local Linux host for the first runnable stack.
- Multiple local Linux hosts later, where ingestion/buffer/switching stay close
  to media.
- Cloud or remote GPU VMs later for transcription or model inference through
  API/config boundaries.

The design should answer:

- Whether the first audio extractor tails the same SRS RTMP/SRT streams as the
  buffer worker or reads from buffer segments.
- How audio references map to stable `stream_id` values.
- Which timestamp source becomes the canonical transcript clock.
- How reconnects, gaps, late audio chunks, and extractor restarts are surfaced.
- What `AudioInputRef` should contain before calling a Faster-Whisper adapter.
- Which fixture mode can prove stream identity and timestamp propagation without
  live RTMP/SRT input.

Expected outputs from this plan ticket:

- One or more implement tickets for audio extraction code and tests.
- Any prerequisite backlog tickets if timebase/session semantics need to land
  first.
- Documentation references to the chosen first-pass extractor shape.

The resulting implementation should preserve the existing terminal MVP and
should not require OBS, Docker, FFmpeg, SRS, Faster-Whisper, or network access
for unit tests.
