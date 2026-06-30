description: Recent transcript fragments from the same player are now joined before local trigger detection so split callouts can reach the AI director.
prereq: prefilter-live-eval-gaming-callouts
files: ai-stream-director/src/services/ai.py, ai-stream-director/tests/test_service_boundaries.py, ai-stream-director/tests/test_runtime_event_pipeline.py
difficulty: medium
----
Implemented same-stream transcript candidate assembly in `TranscriptTriggerPrefilter`.
The prefilter now builds normalized candidate text from recent transcript events
for the newest event's stream, preserving router order and ending at the event
being evaluated. The context window is applied relative to the event being
classified, while `HypeSignal.trigger_time_seconds` still uses
`HypeContext.reference_time_seconds` when provided.

Duplicate suppression now compares the newest assembled candidate against
assembled prior candidates from events inside the duplicate window. Prior
candidates only use events at or before that prior event, so a newest fragment
cannot make an older event appear to have already matched. Suppression remains
global across streams by comparing candidate text and matched trigger phrases.

No production changes were needed in `TranscriptRouter` or `main.py`; the runtime
path already routes final events into recent history and passes
`get_recent_events()` plus the newest message timestamp to the prefilter.

## Validation

- Added service-boundary coverage for split same-stream acceptance, context
  window cutoff rejection, stream-boundary rejection, repeated split phrase
  suppression, cross-stream repeated split phrase suppression, and existing
  filler/reference-time behavior.
- Added runtime coverage proving `process_transcript_event` rejects the first
  split fragment, calls `AIDirector.decide` on the second fragment, anchors the
  candidate signal to the second event timestamp, and passes the router's normal
  recent transcript text.
- Ran from `ai-stream-director`:
  `python -m unittest tests.test_service_boundaries tests.test_runtime_event_pipeline`
  Result: 42 tests passed.

## Review focus

- Confirm the context-window anchor is appropriate: candidate assembly uses the
  evaluated transcript event's end time, while signal output keeps the optional
  reference time. This preserves the existing reference-time test and matches
  the ticket's edge case that the window is relative to the newest event.
- Check whether duplicate suppression should ignore non-signal prior candidates
  earlier in the duplicate window. The current implementation compares every
  prior assembled candidate, which is consistent with the existing duplicate
  behavior and allows split phrase repeats to be suppressed.
