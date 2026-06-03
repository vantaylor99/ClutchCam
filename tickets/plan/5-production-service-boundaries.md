description: Define production service package boundaries and interfaces
prereq:
files: README.md, docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/src/contracts.py, ai-stream-director/src/config.py
----
The repo needs a clear service layout before adding ingestion, buffering,
transcription, AI orchestration, and switcher playback code. The existing
`ai-stream-director` MVP should remain runnable while new production services
are introduced behind stable interfaces.

The architecture should define where service code, shared contracts, test
fixtures, sample media, and deployment files belong. The implementation should
avoid coupling orchestration logic to whether inference runs in local Docker,
local host processes, or a remote GPU endpoint.

Expected behavior:
- Preserve the current MVP command-line workflow.
- Establish importable modules for ingestion, buffer, transcription, AI, and
  switcher boundaries.
- Keep shared event contracts in one place.
- Document how each service communicates with the others.
- Add tests that prove the service boundary modules can be imported without
  requiring OBS, FFmpeg, media inputs, or AI services.
