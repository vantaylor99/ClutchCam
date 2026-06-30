description: Group nearby speech from the same player before trigger checks so reactions are judged by what was said, not by speech-to-text chunk boundaries.
prereq: transcript-prefilter-recent-context-boundaries
files: ai-stream-director/src/transcript_router.py, ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/src/services/ai.py, ai-stream-director/.env.example, docs/ARCHITECTURE.md, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/tests/test_runtime_event_pipeline.py, ai-stream-director/tests/test_service_boundaries.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_runtime_healthcheck_entrypoints.py
difficulty: medium
----
Speech-to-text providers can split one spoken reaction across several final
events, such as `holy` followed by `cow`. The runtime should evaluate a
bounded utterance candidate for each stream instead of treating provider event
boundaries as the semantic boundary.

Add a small assembly layer owned by `TranscriptRouter`. Keep raw transcript
history available for audit and timing, and derive assembled candidates from
the currently bounded history whenever the runtime asks for them. Do not replace
the raw history with assembled text.

## Router model

Extend `TranscriptMessage` so raw events preserve both original
`start_time_seconds` and `end_time_seconds`. Terminal input from
`parse_line(...)` can set both values to the current wall-clock timestamp.
`add_event(...)` should continue rejecting unknown streams, blank text, and
events whose end precedes their start, but accepted live events must retain the
event start and end timestamps. `get_recent_events()` should return raw events
with those preserved timestamps.

Add an assembled candidate dataclass in `transcript_router.py`, for example
`TranscriptUtteranceCandidate`, with:

- `stream_id`
- assembled `text`
- `start_time_seconds` from the first source message
- `end_time_seconds` from the last source message
- `source_event_count`
- source span metadata such as `source_start_index` and `source_end_index`,
  relative to the current recent raw history returned by `get_recent_messages()`

Expose router APIs along these lines:

- `get_recent_utterance_candidates() -> tuple[TranscriptUtteranceCandidate, ...]`
- `get_recent_candidate_events() -> tuple[TranscriptEvent, ...]`, converting
  candidates into transcript-shaped events for `HypeContext`
- `get_recent_context_text()` should render assembled candidate lines, not one
  line per raw provider fragment

It is acceptable to keep the prefilter interface as `Sequence[TranscriptEvent]`;
the key runtime contract is that those events now represent bounded assembled
utterances.

## Assembly rules

Build candidates in chronological order from `get_recent_messages()` so the
existing history seconds and message-count caps still bound memory. Start a new
candidate before adding the next message when any of these conditions is true:

- stream ID changes
- the gap from the current candidate's end to the next message start exceeds
  `TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS`
- adding the next message would make the candidate duration exceed
  `TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS`
- the current candidate text ends with strong sentence punctuation such as `.`,
  `!`, or `?`
- adding the next message would exceed `TRANSCRIPT_UTTERANCE_MAX_CHARACTERS`
- the candidate already has `TRANSCRIPT_UTTERANCE_MAX_EVENTS` source messages

Join source texts with a single space after trimming each raw text. Preserve the
candidate end timestamp as the newest contributing raw event's end timestamp;
this is the trigger time used for lookback clips.

Use conservative defaults:

- `TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS=2.0`
- `TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS=8.0`
- `TRANSCRIPT_UTTERANCE_MAX_CHARACTERS=240`
- `TRANSCRIPT_UTTERANCE_MAX_EVENTS=8`

Add these settings to `AppConfig`, `get_config()`, `validate_config(...)`,
`.env.example`, and docs. Validate the time and character/event bounds as
positive values. Wire them into `TranscriptRouter(...)` construction in
`main.main()`.

## Runtime behavior

`main.process_transcript_event(...)` should still reject partial events before
they reach the router. After a final event or terminal line is accepted,
`evaluate_accepted_transcript(...)` should classify assembled candidates:

- call the router's candidate-event API, not raw `get_recent_events()`
- pass the newest assembled candidate end time as `reference_time_seconds`
- continue returning/logging the accepted raw `TranscriptMessage`
- send `TranscriptRouter.get_recent_context_text()` to `AIDirector.decide(...)`,
  now rendered as assembled lines like `player_2: holy cow`

Repeated speech-to-text output should be bounded by the assembly limits before
duplicate detection runs. For example, repeated short fragments inside one
utterance should produce one candidate, and repeated assembled candidates inside
the duplicate window should not repeatedly trigger switch attempts.

Terminal/manual input must keep using the same router path. A single manual line
forms a one-message candidate; consecutive same-stream manual lines may assemble
when they are within the configured gap, duration, character, and source-event
bounds.

## Edge cases & interactions

- Partial live transcript events remain ignored and must not alter raw history
  or candidates.
- Raw event timestamps must survive assembly; tests should assert both start
  and end times from `get_recent_events()`.
- A stream change always splits candidates, even when timestamps are close.
- A long silence splits candidates based on event timestamps, not wall-clock
  receive time.
- Maximum duration, text length, and source-event count split before the
  overflowing event so oversized candidates are not emitted.
- Sentence-ending punctuation on the current candidate splits before the next
  event, but punctuation inside a fragment such as a comma should not.
- Candidate assembly is recomputed from trimmed recent history; when raw
  history expires or is capped by message count, candidates should reflect only
  remaining raw messages.
- Scheduler gates still run before classification and AI calls; AI-disabled and
  cooldown paths should accept raw messages without calling the director.
- The prefilter's existing direct tests can continue to cover raw
  `TranscriptEvent` sequences, but runtime tests must prove the orchestrator
  passes assembled candidate events/text.
- Lookback clip requests must use the assembled candidate end timestamp, not the
  first source event time.
- Logging accepted transcript text should continue to log the raw accepted
  message text and remain off by default.

## Tests

Add or update focused tests:

- Router tests in `test_transcription_event_api.py` for same-stream short-gap
  assembly, long-gap split, stream-change split, duration split, punctuation
  split, character bound split, event-count bound split, and raw event timestamp
  preservation.
- Runtime tests in `test_runtime_event_pipeline.py` proving `holy` + `cow`
  reaches the AI director as `player_2: holy cow`, with trigger time from the
  second raw event.
- Runtime duplicate tests showing repeated assembled utterances inside the
  duplicate window do not create repeated AI calls.
- Terminal input tests in `test_dry_run_obs.py` proving manual lines still
  parse, route, assemble, and evaluate through the same behavior.
- Config tests in `test_dry_run_obs.py` and
  `test_runtime_healthcheck_entrypoints.py` for defaults, env overrides, and
  validation errors for non-positive utterance bounds.
- Documentation assertions, if existing tests cover docs/env content, should be
  updated for the new settings.

## TODO

- Update `TranscriptMessage` and add the router-owned utterance candidate model.
- Implement bounded candidate assembly and assembled context rendering in
  `transcript_router.py`.
- Wire utterance settings through config, `.env.example`, docs, and router
  construction.
- Switch runtime prefilter and AI context calls to assembled candidate events.
- Add and update tests for router boundaries, runtime behavior, terminal input,
  config validation, and docs/env expectations.
- Run the focused test files touched by this change, then run the broader
  project test command if it is agent-runnable.
