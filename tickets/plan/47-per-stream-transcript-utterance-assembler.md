description: Group nearby speech from the same player before trigger checks so reactions are judged by what was said, not by speech-to-text chunk boundaries.
prereq: transcript-prefilter-recent-context-boundaries
files: ai-stream-director/src/contracts.py, ai-stream-director/src/transcript_router.py, ai-stream-director/src/services/ai.py, ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/.env.example, docs/ARCHITECTURE.md, ai-stream-director/tests/test_service_boundaries.py, ai-stream-director/tests/test_runtime_event_pipeline.py, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/tests/test_dry_run_obs.py
difficulty: medium
----
Speech-to-text providers do not always emit one complete sentence per final
transcript event. A single phrase can arrive as several final events such as
`holy` then `cow`, while a fixed audio chunk can also produce one broad text
blob. The trigger path should evaluate a bounded utterance candidate for each
stream instead of treating the provider event boundary as the semantic boundary.

The current runtime path is:

- `main.process_transcript_event(...)` rejects partial events, then calls
  `TranscriptRouter.add_event(...)`.
- `TranscriptRouter` stores one `TranscriptMessage` per accepted event and
  exposes raw-event-shaped history through `get_recent_events()`.
- `evaluate_accepted_transcript(...)` passes those events to
  `TranscriptTriggerPrefilter.classify(...)`, then sends
  `TranscriptRouter.get_recent_context_text()` to `AIDirector.decide(...)` when
  the local prefilter finds a candidate.
- Terminal input already flows through `TranscriptRouter.parse_line(...)` and
  should keep working as a transcript source.

Plan the feature around a small router-owned assembly layer that derives recent
utterance candidates from accepted final events. Preserve the raw transcript
events and their original start/end timestamps for auditability and lookback
timing; do not overwrite the raw message history with assembled text.

The assembled candidate model should include:

- `stream_id`
- assembled `text`
- `start_time_seconds` from the first source event
- `end_time_seconds` from the last source event
- source event count or source event span metadata so tests and future logs can
  prove which raw events contributed

The router should split candidates when any of these boundaries are crossed:

- the stream ID changes
- the gap between same-stream events exceeds a configurable silence threshold
- adding the next event would exceed a configurable maximum utterance duration
- punctuation strongly suggests the prior thought ended, when punctuation is
  available
- text length or source-event count reaches configured bounds

The router should still trim old raw messages by the existing transcript
history window and message count. Candidate assembly should run from the current
bounded history so it cannot grow unbounded state.

Configuration should expose conservative defaults through `AppConfig`,
`.env.example`, and docs. Suggested knobs:

- `TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS`
- `TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS`
- `TRANSCRIPT_UTTERANCE_MAX_CHARACTERS`
- optionally `TRANSCRIPT_UTTERANCE_MAX_EVENTS` if character and duration bounds
  are not enough to cap repeated short ASR output

The prefilter should evaluate assembled candidates as the primary semantic
units. It may continue accepting raw `TranscriptEvent` sequences internally if
that keeps the interface small, but the runtime path should pass candidate
events/text that already represent the assembled utterance for the newest
accepted transcript. Duplicate detection should compare bounded candidate text
so repeated ASR output cannot repeatedly trigger switches.

The AI prompt context should remain readable and ordered. Prefer context lines
that show assembled recent utterances, for example `player_2: holy cow`, while
still retaining raw timestamps in the candidate data used for trigger time and
clip lookback. The positive trigger time should remain the assembled
candidate's end timestamp, which is the end time of the newest contributing raw
event.

Terminal/manual transcript input must keep using the same router path. A manual
line has identical start and end timestamps today, so it should form a
single-event candidate unless subsequent same-stream manual lines arrive within
the configured gap and duration bounds.

Expected tests for the plan to cover:

- same-stream short-gap events assemble into one candidate and trigger phrases
  split across provider events reach both the prefilter and AI director
- long gaps, stream changes, maximum duration, punctuation, and maximum text
  length split candidates
- raw recent events are still available with their original timestamps after
  assembly
- the AI context uses assembled utterance lines rather than one line per raw
  provider fragment
- repeated long or noisy ASR output is bounded and does not create repeated
  switch attempts
- terminal input continues to parse, route, and evaluate through the same
  behavior
- config defaults and validation cover the new utterance settings
