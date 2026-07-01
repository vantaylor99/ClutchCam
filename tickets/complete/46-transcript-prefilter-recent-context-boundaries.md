description: Recent transcript fragments from the same player are now joined before local trigger detection so split callouts can reach the AI director.
prereq: prefilter-live-eval-gaming-callouts
files: ai-stream-director/src/services/ai.py, ai-stream-director/tests/test_service_boundaries.py, ai-stream-director/tests/test_runtime_event_pipeline.py
difficulty: medium
----
Implemented and reviewed same-stream transcript candidate assembly in `TranscriptTriggerPrefilter`.

The prefilter now builds normalized candidate text from recent transcript events for the newest event's stream, preserving router order and ending at the event being evaluated. The context window is applied relative to the transcript event being classified, while `HypeSignal.trigger_time_seconds` still uses `HypeContext.reference_time_seconds` when provided.

Duplicate suppression compares the newest assembled candidate against assembled prior candidates from events inside the duplicate window. Prior candidates only use events at or before that prior event, so a newest fragment cannot make an older event appear to have already matched. Suppression remains global across streams by comparing candidate text and matched trigger phrases.

## Review findings

- Checked the implement commit `b197627b025e338698664ff892bc345f609e49c8`, the current `TranscriptTriggerPrefilter` logic, runtime transcript routing through `process_transcript_event`, and the service/runtime tests.
- Found and fixed one review issue: the initial same-stream assembly could let an older trigger phrase in recent context drive the newest event. That could re-trigger stale context after the duplicate window or suppress a newer same-stream phrase because `_matched_hype_phrase` found the older phrase first.
- Fixed inline by matching only phrases that overlap the newest transcript event's normalized text span. Split phrases still work because a phrase spanning the previous fragment and newest fragment overlaps the newest span.
- Added regression coverage for stale context not re-triggering, newer same-stream phrases after an older trigger still being accepted, and short `help` callouts still working when prior same-stream context exists.
- No major findings remain. No backlog, fix, plan, blocked, or tripwire tickets were created.

## Validation

Ran from `ai-stream-director`:

- `python -m py_compile src/services/ai.py`
- `python -m unittest tests.test_service_boundaries tests.test_runtime_event_pipeline`
  - Result: 45 tests passed.
- `python -m unittest discover -s tests`
  - Result: 287 tests passed.
