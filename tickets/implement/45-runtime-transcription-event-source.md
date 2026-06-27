description: Feed live transcription events into the orchestrator runtime loop
prereq: transcription-ffmpeg-supervision
files: ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/transcript_router.py, ai-stream-director/tests/test_runtime_event_pipeline.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/tests/test_dry_run_obs.py
----
The normalized transcript-to-director path already exists, but `main.main()`
only reads terminal lines. `RuntimeTranscriptEventHandler` can consume
`TranscriptEvent` values and route them through `TranscriptRouter.add_event(...)`,
the local trigger prefilter, AI director, scheduler, and optional output
switcher. Separately, `transcription_worker.TranscriptionWorker` owns audio
extraction, chunk discovery, transcription, and sink delivery. Its default
entrypoint sink writes JSON lines to stdout with these event types:

- `transcript_event` with `stream_id`, `text`, `start_time_seconds`,
  `end_time_seconds`, and `is_final`.
- `transcription_failure` with the failed chunk's stream and URI.
- `transcription_worker_error` for process-level startup/runtime failures.

For the first integrated runtime, keep that standalone JSONL worker behavior as
a diagnostics surface, but do not make the orchestrator scrape Docker logs or
cross-container stdout. Instead, add an opt-in orchestrator-owned live
transcription source that runs the same worker/pump boundary in process and
uses a small queue sink to hand events back to the orchestrator loop. This keeps
AI decisions, scheduler mutations, terminal commands, and OBS calls on the main
orchestrator thread.

The live source should be disabled by default so the terminal MVP path and
existing smoke scripts continue to behave exactly as they do today. When
enabled, startup should create the normal router, director, prefilter, scheduler,
and dry-run/real OBS controller first, then start live transcription only after
AI readiness and OBS startup succeed. Shutdown paths such as `/quit`, EOF,
KeyboardInterrupt, and startup failure must stop the transcription source and
its FFmpeg children.

Partial transcript handling for this checkpoint is intentionally conservative.
`TranscriptEvent.is_final` must be preserved by the worker output/parser, but
only final events should be eligible for router history and AI decisions in this
ticket. Current `TranscriptRouter.add_event(...)` stores a `TranscriptMessage`
and `TranscriptMessage.to_event()` always returns `is_final=True`, so routing
partials would lose their status and could trigger duplicate or unstable model
calls. Partial-event context can be designed later if live Faster-Whisper output
proves it is useful.

Backpressure should be bounded at the orchestrator edge. The worker thread must
not call the AI director directly. A full queue should reject or drop the newest
live transcript event with a clear log line and without crashing the worker.
Do not add cross-chunk text deduplication in this ticket; rely on
`CompletedAudioChunkDiscovery` for chunk-level once-only processing and on the
existing local prefilter duplicate window for obvious repeated phrases.

Expected behavior:

- With live transcription disabled, `python src/main.py`, terminal transcript
  lines, manual commands, `scripts/smoke_orchestrator_dry_run.py`, and existing
  tests keep their current behavior.
- With live transcription enabled, final `TranscriptEvent` values from the
  transcription runtime are processed by `RuntimeTranscriptEventHandler`.
- AI-disabled mode and scheduler cooldown still accept final transcript history
  but skip model calls, matching terminal input behavior.
- Local prefilter rejection, AI escalation, decision handling, and scheduler
  application are shared between terminal input and live transcript events.
- Buffered `SwitcherTarget` construction remains optional. Do not instantiate a
  buffer-backed or OBS media-source output switcher in this ticket.
- Standalone `python -m transcription_worker` JSONL output shape remains
  backwards compatible for debugging and future process-boundary work.

Validation should stay unit-level and bounded. Do not require Docker, FFmpeg,
OBS, Faster-Whisper, Ollama, or live media inputs.

TODO:

- Add app config for opt-in live transcription, including an enabled flag and a
  bounded queue size. Keep defaults disabled and conservative.
- Add a queueing transcript sink/source in `main.py` or a small helper module
  that accepts `TranscriptEvent` values, enqueues final events, ignores or logs
  partial events, and returns `None` when the event was not accepted.
- Wire the orchestrator loop to drain terminal input and live transcript events
  while continuing to call `scheduler.tick()`.
- Build the live source from the existing transcription worker/runtime
  components without changing the standalone JSONL event shape.
- Ensure all orchestrator exit paths stop the live source and extractor
  lifecycle exactly once.
- Add tests with fake transcription sources proving final-event routing,
  partial-event ignore behavior, queue-full rejection, shutdown cleanup, and no
  regression to terminal commands or dry-run smoke behavior.
