description: Completed local transcript trigger prefiltering before Gemma escalation
prereq: transcription-event-api, ai-disabled-skips-model-call
files: ai-stream-director/src/services/ai.py, ai-stream-director/src/transcript_router.py, ai-stream-director/src/ai_director.py, ai-stream-director/src/scheduler.py, ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/.env.example, ai-stream-director/tests/test_service_boundaries.py, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/tests/test_ai_director.py, ai-stream-director/tests/test_dry_run_obs.py
----
Local transcript prefiltering now gates Gemma/Ollama escalation.

Built:

- Added `TranscriptTriggerPrefilter` and `TranscriptTriggerPrefilterConfig` in
  `services.ai`, keeping that service boundary standard-library-only.
- The prefilter emits `HypeSignal` candidates for clear local hype phrases and
  suppresses filler, short/noise-like text, disabled classifiers, and recent
  duplicate trigger phrases across streams.
- Added configurable runtime defaults through `AppConfig` and `.env.example`:
  enabled flag, minimum text length, duplicate window, context window, and
  minimum local confidence.
- Added `TranscriptRouter.get_recent_events()` so terminal input and future
  `TranscriptEvent` runtime paths can share the same candidate context.
- Added `SceneScheduler.ai_evaluation_gate()` so model calls can be skipped
  before Gemma/Ollama when AI mode is off or switch cooldown is active.
- Updated `main.process_line(...)` to preserve accepted transcript history, then
  skip model evaluation for disabled AI, active cooldown, or no local trigger.
- Added `evaluate_accepted_transcript(...)` as the shared orchestration helper
  for accepted terminal messages and future runtime events.
- Extended `AIDirector.decide(...)` and `_build_prompt(...)` with an optional
  `candidate_signal` so the newest stream/time/reason is represented separately
  from rolling transcript context.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_service_boundaries tests.test_transcription_event_api tests.test_ai_director tests.test_dry_run_obs tests.test_transcription_runtime -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest discover -s tests -v
git diff --check
```

Result:

- Focused combined suite: 60 tests passed.
- Full Python unit suite: 93 tests passed.
- `git diff --check`: passed; only CRLF normalization warnings were reported.
