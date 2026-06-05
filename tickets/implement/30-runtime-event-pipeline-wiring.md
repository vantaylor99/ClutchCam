description: Wire transcription events into AI and buffered switch orchestration
prereq: transcription-worker-runtime-entrypoint, transcript-trigger-prefilter, buffered-switcher-playback
files: ai-stream-director/src/main.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/transcription_runtime.py, ai-stream-director/src/services/switcher.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_runtime_event_pipeline.py, docs/ARCHITECTURE.md
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

TODO:

- Add an import-safe event handling boundary that accepts `TranscriptEvent`
  objects and reuses the existing transcript router, prefilter, AI director, and
  scheduler logic.
- Keep existing terminal `player_N: text` behavior unchanged.
- Add tests proving event timestamps drive `HypeSignal.trigger_time_seconds`.
- Add tests proving AI-off and cooldown gates skip model calls for runtime
  events.
- Add tests proving accepted AI decisions can build buffered switch targets
  without requiring live FFmpeg, OBS, or Docker.
- Update architecture docs only for the runtime event path landed in this
  ticket.
