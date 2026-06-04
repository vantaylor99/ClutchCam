description: Wire transcription events into AI and buffered switch orchestration
prereq: transcription-worker-runtime-entrypoint, transcript-trigger-prefilter, buffered-switcher-playback
files: ai-stream-director/src/main.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/transcription_runtime.py, ai-stream-director/src/services/switcher.py, docs/ARCHITECTURE.md
----
The terminal MVP still accepts typed transcript lines even though worker
entrypoints and service boundaries now exist. The runtime needs a production
event path that can feed timestamped transcript events into the router, local
prefilter, AI director, and buffer-backed switcher.

Expected behavior:
- Consume normalized transcript events from a worker-safe boundary rather than
  only terminal input.
- Preserve stream identity and media timestamps from `TranscriptEvent`.
- Use the local prefilter before model calls.
- Build buffered switch targets from accepted `HypeSignal` values.
- Keep terminal MVP and dry-run mode available for operator testing.
