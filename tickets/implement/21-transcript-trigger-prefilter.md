description: Implement local transcript trigger prefiltering before Gemma escalation
prereq: transcription-event-api, ai-disabled-skips-model-call
files: ai-stream-director/src/contracts.py, ai-stream-director/src/services/ai.py, ai-stream-director/src/transcript_router.py, ai-stream-director/src/ai_director.py, ai-stream-director/src/scheduler.py, ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/tests/test_service_boundaries.py, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/tests/test_ai_director.py, ai-stream-director/tests/test_dry_run_obs.py
----
Insert a cheap local transcript prefilter between accepted transcript history and
Gemma/Ollama escalation. The prefilter should evaluate the newest accepted
terminal transcript line or `TranscriptEvent` together with a bounded recent
event window, then either return a candidate `HypeSignal` or skip model
evaluation entirely.

The candidate signal is the handoff contract between local transcript rules and
the model adapter:

- `stream_id` is the speaker/stream that produced the newest accepted trigger.
- `trigger_time_seconds` is the terminal message timestamp or
  `TranscriptEvent.end_time_seconds`.
- `confidence` is the local prefilter confidence, independent from the later
  model decision confidence.
- `reason` is a short local explanation such as matched excitement phrase,
  urgent phrase, or repeated hype cue.
- `source` remains `"transcript"`.

Current runtime seams:

- `contracts.HypeSignal` and `contracts.TranscriptEvent` already exist.
- `services.ai.HypeContext` accepts transcripts and an optional
  `reference_time_seconds`; `services.ai` must stay standard-library-only and
  must not import runtime clients, `main`, `scheduler`, `transcript_router`, or
  `requests`.
- `TranscriptRouter.parse_line(...)` and `TranscriptRouter.add_event(...)`
  return `TranscriptMessage` values and append accepted messages to rolling
  history before any model decision.
- `main.process_line(...)` currently owns the terminal orchestration path.
- `AIDirector.decide(...)` currently accepts raw rolling transcript text and its
  prompt does not distinguish the newest trigger from older context.
- `SceneScheduler.apply_ai_decision(...)` remains the final defensive gate, but
  model evaluation should also be skipped before Gemma when AI is disabled or
  switch cooldown makes a new model decision unusable.

Implementation notes:

- Prefer a small concrete classifier/prefilter in `services.ai` if it can remain
  standard-library-only. A new standard-library-only module is acceptable if it
  keeps the service boundary cleaner.
- Keep phrase lists, minimum text/token thresholds, recent duplicate windows,
  bounded history windows, cooldown windows, and confidence thresholds
  configurable through `AppConfig` fields where runtime wiring needs them, or
  through explicit constructor parameters where testability is enough.
- Suppress obvious low-signal utterances before model escalation, including
  blank/noise-like text, very short fragments, filler, acknowledgements, and
  repeated/recent duplicate phrases both per stream and across streams.
- Preserve transcript history even when local prefiltering, disabled AI, or
  cooldown gates skip the model call.
- Ground model escalation in the candidate stream and trigger time. Extend the
  director input or prompt so the candidate event is represented separately from
  rolling context; older multi-player history must not displace the newest
  accepted trigger.
- Keep terminal input and future runtime `TranscriptEvent` input on the same
  orchestration path where practical. If a shared helper is introduced, have it
  consume the accepted `TranscriptMessage`, recent messages, scheduler gate, and
  prefilter result rather than reparsing text.

Open coordination:

- Coordinate with `ai-disabled-skips-model-call`, currently represented by
  `tickets/review/19-ai-disabled-skips-model-call.md` at validation time. Follow
  the slug if that ticket moves again. Reuse its scheduler or
  `main.process_line(...)` disabled-AI gate once it lands; do not add a
  competing disabled-AI check that prints different terminal behavior.
- This ticket should extend the same pre-call gating concept to active switch
  cooldown. A small non-mutating scheduler helper/status result is preferable to
  relying on `apply_ai_decision(...)` side effects.

TODO:

- Add focused unit coverage for the local transcript prefilter accepting clear
  hype phrases and rejecting fillers, acknowledgements, blank or short
  noise-like text, and recent duplicate phrases per stream and across streams.
- Add tests proving the prefilter emits `HypeSignal` candidates with the newest
  stream ID, `source="transcript"`, a useful reason, and
  `trigger_time_seconds` from `TranscriptMessage.timestamp` for terminal input.
- Extend router/event coverage so candidates generated from
  `TranscriptRouter.add_event(...)` use `TranscriptEvent.end_time_seconds`.
- Add or extend scheduler/orchestration tests proving accepted transcript
  history is preserved while disabled AI and active cooldown skip
  `AIDirector.decide(...)`.
- Wire the prefilter into `main.process_line(...)` after transcript acceptance
  and before building model input or calling the director.
- Add configurable defaults in `AppConfig` or constructor parameters for local
  phrase/threshold/window behavior, keeping env parsing simple and covered where
  runtime env fields are added.
- Extend `AIDirector.decide(...)` and `_build_prompt(...)` or introduce a small
  director request type so candidate stream/time/reason are distinct from
  rolling transcript context. Preserve compatibility for existing call sites or
  update them deliberately.
- Add AI director prompt/input tests proving candidate stream and trigger time
  are present separately from recent context.
- Keep `services.ai` import-boundary tests passing without importing runtime
  clients or network dependencies.
- Run focused unittest coverage with bytecode disabled, for example
  `python -B -m unittest tests.test_service_boundaries tests.test_transcription_event_api tests.test_ai_director tests.test_dry_run_obs -v`, after dependencies are available in the active Python environment.
