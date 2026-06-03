description: Extract per-stream audio for real-time transcription
prereq: local-media-server-ingest
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/src/contracts.py
----
The transcription service needs clean per-stream audio input before it can call
Faster-Whisper. This work should define and implement how audio is extracted
from each live input while preserving stream identity and low latency.

Expected behavior:
- Extract audio for each configured stream ID.
- Feed audio chunks or streams to a transcription adapter without blocking video
  buffering.
- Keep extraction restartable when a source disconnects and reconnects.
- Provide fixture-based tests for stream identity and timestamp propagation.
