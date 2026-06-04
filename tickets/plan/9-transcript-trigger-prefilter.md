description: Plan local transcript trigger prefiltering before model escalation
prereq: transcription-event-api
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/src/contracts.py, ai-stream-director/src/services/ai.py, ai-stream-director/src/transcript_router.py, ai-stream-director/src/ai_director.py, ai-stream-director/src/scheduler.py, ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/tests/test_service_boundaries.py, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/tests/test_ai_director.py, ai-stream-director/tests/test_dry_run_obs.py
----
The production AI path should insert a cheap local transcript prefilter between
accepted transcript events and Gemma escalation. The prefilter decides whether
the newest accepted transcript event is worth model evaluation, emits a
candidate `HypeSignal` when local rules find a likely trigger, and carries the
candidate stream/time forward so model prompting or later switching stays
grounded in the event that caused escalation.

Current architecture:

- `TranscriptEvent` and `HypeSignal` are shared contracts in `contracts.py`.
- `services.ai.HypeContext` already accepts transcripts and optional
  `reference_time_seconds`, but no concrete local classifier or prefilter
  exists.
- `TranscriptRouter.parse_line(...)` and `TranscriptRouter.add_event(...)`
  currently return `TranscriptMessage` values. `add_event(...)` uses
  `TranscriptEvent.end_time_seconds` as the message timestamp and receipt time
  for history retention.
- `main.process_line(...)` calls
  `ai_director.decide(transcript_router.get_recent_context_text())` for every
  accepted terminal transcript line.
- `SceneScheduler.apply_ai_decision(...)` enforces `ai_enabled`, confidence,
  and switch cooldown after the model call. There is no public non-mutating
  helper for deciding whether model evaluation is useful before escalation.
- `AIDirector.decide(...)` accepts only raw context text, and its prompt does
  not identify candidate stream or trigger time separately from rolling
  context.
- Existing tests cover AI parsing/readiness, scheduler focus/cooldown,
  transcript event normalization/router behavior, and service-boundary imports.

Requirements:

- Evaluate the newest accepted transcript event together with a bounded recent
  event window before calling Gemma.
- Emit optional `HypeSignal` candidates for likely hype moments using stream ID,
  trigger timestamp, confidence, reason, and source `transcript`.
- Suppress obvious low-signal utterances, including fillers, acknowledgements,
  very short noise, and repeated/recent duplicate phrases per stream and across
  streams.
- Keep phrase lists, repeat windows, history windows, cooldown windows, and
  confidence thresholds configurable through `AppConfig` fields or explicit
  testable constructor parameters.
- Check scheduler state before any Gemma call so disabled AI and active switch
  cooldown can skip model evaluation entirely. Coordinate with
  `ai-disabled-skips-model-call` if that fix has landed first.
- Preserve transcript history even when model escalation is skipped, so later
  accepted lines still have rolling context.
- Ground model escalation in the candidate stream and trigger time. The prompt
  or director input should distinguish the candidate event from recent context
  so older multi-player history cannot displace the newest accepted trigger.
- Keep terminal input and future `TranscriptEvent` runtime input on the same
  orchestration path where practical.

Test expectations:

- Unit tests for the local prefilter accepting clear hype phrases and rejecting
  fillers, blank or noise-like short text, repeated phrases, disabled-AI gates,
  and cooldown gates.
- Router/event tests showing candidate signals use
  `TranscriptEvent.end_time_seconds` or the terminal message timestamp as
  `trigger_time_seconds`.
- `main.process_line(...)` or orchestration tests proving skipped events do not
  call `AIDirector.decide(...)`, while accepted candidates do.
- AI director prompt/input tests proving candidate stream/time is represented
  separately from rolling context.
- Existing service-boundary import tests should still pass without importing
  runtime clients from `services.ai`.

Potential implementation location:

- Prefer a small concrete classifier/prefilter in
  `ai-stream-director/src/services/ai.py` or a new standard-library-only module
  imported by runtime code.
- Avoid baking prefilter rules into `AIDirector` parsing logic; `AIDirector`
  should remain the model adapter and consume already-selected context.
- Scheduler may need a non-mutating public status/helper for "model evaluation
  is currently useful" instead of relying on side effects and print-only
  behavior in `apply_ai_decision(...)`.

Open coordination:

- `tickets/fix/19-ai-disabled-skips-model-call.md` covers the narrower
  disabled-AI skip for terminal input. If it lands first, reuse its scheduler or
  main entry point rather than adding a competing check.
