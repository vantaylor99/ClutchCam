description: Join recent transcript fragments from one player before local trigger detection so split callouts can still reach the AI director.
prereq: prefilter-live-eval-gaming-callouts
files: ai-stream-director/src/services/ai.py, ai-stream-director/src/main.py, ai-stream-director/src/transcript_router.py, ai-stream-director/tests/test_service_boundaries.py, ai-stream-director/tests/test_runtime_event_pipeline.py
difficulty: medium
----
The transcript prefilter currently classifies only the newest transcript event's
text. Speech recognition and fixed audio chunking can split a natural phrase
across adjacent final transcript events, for example `holy` followed by `cow`.
When that happens the local prefilter rejects the newest event before the AI
director sees the recent transcript context.

Change `TranscriptTriggerPrefilter` so trigger detection evaluates a bounded
same-stream candidate context ending at the newest event:

- Keep `HypeContext.transcripts` as the input. `evaluate_accepted_transcript`
  already passes `transcript_router.get_recent_events()` and
  `reference_time_seconds=message.timestamp`, so the runtime path has the data
  needed for this feature.
- In `TranscriptTriggerPrefilter.classify`, derive a candidate event sequence
  from `context.transcripts` that:
  - includes only events whose `stream_id` matches the newest event,
  - preserves chronological order,
  - ends at the newest event,
  - excludes events older than `trigger_time - context_window_seconds` when the
    configured context window is positive,
  - follows the current zero-window behavior consistently with
    `_recent_history` unless the implementation intentionally tightens that
    behavior and updates tests for it.
- Normalize `" ".join(event.text for event in candidate_events)` and use that
  joined candidate text for `_is_signal_text`, `_matched_hype_phrase`,
  confidence, and reason generation. The returned `HypeSignal.stream_id` remains
  the newest event's stream, and `trigger_time_seconds` remains
  `context.reference_time_seconds` when provided, otherwise
  `newest.end_time_seconds`.

Duplicate suppression must use the same candidate concept as trigger detection.
If a phrase was detected from split fragments, a later repeated split phrase
inside the duplicate window should still be suppressed. A defensible approach:

- Keep duplicate suppression global across streams, matching existing tests that
  reject repeated phrases on a different player.
- For each prior transcript event inside the duplicate window, assemble that
  prior event's own bounded same-stream candidate text from events at or before
  the prior event.
- Treat the newest candidate as a duplicate when either normalized candidate
  text matches exactly or `_same_hype_phrase` finds the same configured trigger
  phrase between the newest candidate and a prior assembled candidate.
- Do not let events after the prior event contribute to the prior candidate.
  Otherwise the newest fragment could make an older event look like it had
  already triggered.

`TranscriptRouter` does not need new production behavior unless the
implementation finds a cleaner boundary for same-stream candidate assembly.
It already stores final routed events in timestamp order and exposes them
through `get_recent_events()`.

## Edge cases & interactions

- Split phrase acceptance: `player_2: holy` followed by `player_2: cow` should
  trigger on the second event even though neither event's text alone contains
  the full phrase.
- Window boundary: a same-stream fragment older than
  `TRANSCRIPT_PREFILTER_CONTEXT_SECONDS` relative to the newest event must not
  contribute to the newest candidate.
- Stream boundary: `player_1: holy` followed by `player_2: cow` must not trigger
  because fragments from different streams are not joined for detection.
- Duplicate boundary: a repeated complete phrase and a repeated split phrase
  inside `TRANSCRIPT_PREFILTER_DUPLICATE_WINDOW_SECONDS` should be rejected,
  including when the repeat happens on another stream.
- Trigger time: `HypeSignal.trigger_time_seconds` must stay anchored to
  `HypeContext.reference_time_seconds` when present, and otherwise to the newest
  event's `end_time_seconds`; do not anchor to the first fragment in a joined
  phrase.
- Filler and noise: routine filler such as `yeah` and short non-signal text must
  remain rejected without calling the AI director.
- Ordering assumptions: `HypeContext.transcripts[-1]` remains the newest event
  being evaluated. Helper code should avoid sorting by timestamp unless tests
  explicitly cover the changed behavior, because router order is already the
  contract used by the runtime.
- History trimming: runtime behavior is bounded first by `TranscriptRouter`
  history settings, then by the prefilter context window. Tests should use
  history windows large enough that failures point at the prefilter logic, not
  router trimming.

## Suggested tests

- Add `test_transcript_prefilter_accepts_split_same_stream_hype_phrase` in
  `test_service_boundaries.py`: previous `holy`, newest `cow`, same stream,
  within context window, returns a signal for the newest stream.
- Add `test_transcript_prefilter_rejects_split_phrase_outside_context_window`:
  configure a small `context_window_seconds`, put `holy` before the cutoff and
  `cow` as newest, expect `None`.
- Add `test_transcript_prefilter_does_not_join_other_stream_fragments`: `holy`
  on one player, `cow` on another, expect `None`.
- Add duplicate coverage for split phrases: first `holy`/`cow` pair triggers,
  second same phrase pair inside the duplicate window returns `None` when all
  four events are passed in order. Include a cross-stream repeat if the helper
  structure makes that inexpensive.
- Add or extend a runtime pipeline test in `test_runtime_event_pipeline.py` that
  processes two final transcript events through `process_transcript_event` and
  asserts the AI director is called only after the second event, with the
  candidate signal anchored to the second event's timestamp and the director
  receiving the router's normal recent transcript text.

## TODO

- Refactor `TranscriptTriggerPrefilter` to build normalized candidate text from
  bounded same-stream recent context ending at a chosen event.
- Update duplicate suppression to compare assembled prior candidates, not only
  individual prior event text.
- Add focused boundary tests in `test_service_boundaries.py` for split phrases,
  window cutoffs, stream isolation, duplicate suppression, filler rejection, and
  trigger time anchoring.
- Add runtime coverage in `test_runtime_event_pipeline.py` proving split
  fragments reach `AIDirector.decide` only when the joined same-stream candidate
  contains a trigger phrase.
- Run the relevant test slice from `ai-stream-director`, at minimum:
  `python -m unittest tests.test_service_boundaries tests.test_runtime_event_pipeline`.
