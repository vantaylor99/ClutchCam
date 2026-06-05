description: Completed runtime transcript event pipeline boundary
prereq: transcription-worker-runtime-entrypoint, transcript-trigger-prefilter, buffered-switcher-playback
files: ai-stream-director/src/main.py, ai-stream-director/tests/test_runtime_event_pipeline.py, docs/ARCHITECTURE.md
----
Runtime transcript events now have an import-safe orchestrator boundary.

Built:

- Added `RuntimeTranscriptEventHandler`, a callable sink for normalized
  `TranscriptEvent` objects.
- Added `process_transcript_event(...)` so runtime events can use
  `TranscriptRouter.add_event(...)` without going through terminal text input.
- Reused the existing scheduler AI/cooldown gate, local trigger prefilter, AI
  director call, and terminal logging behavior.
- Added `RuntimeTranscriptEventResult` so tests and future diagnostics can see
  accepted messages, candidate signals, model decisions, buffered targets, and
  switch results.
- Built buffered `SwitcherTarget` values from accepted `HypeSignal` timestamps
  when the AI-selected player scene matches the local trigger stream.
- Preserved the terminal MVP `player_N: text` input path.
- Documented the new runtime event boundary and remaining OBS buffered
  media-source adapter gap.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_runtime_event_pipeline tests.test_dry_run_obs tests.test_buffered_switcher tests.test_service_boundaries -v
```

Result:

- Focused runtime/switcher suite: 54 tests passed.
