<!-- resume-note -->
RESUME: A prior agent run on this ticket did not complete.
  Prior run: 2026-06-30T04:40:14.961Z (agent: codex)
  Log file: C:\ClutchCam\tickets\.logs\47-per-stream-transcript-utterance-assembler.review.2026-06-30T04-40-14-961Z.log
Read the log to see what was done. Resume where it left off.
If the prior run hit a timeout or repeated error, be cautious not to rush into the same situation.
<!-- /resume-note -->
description: Group nearby speech from the same player before trigger checks so reactions are judged by what was said, not by speech-to-text chunk boundaries.
prereq: transcript-prefilter-recent-context-boundaries
files: ai-stream-director/src/transcript_router.py, ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/scripts/latency_soak_harness.py, ai-stream-director/.env.example, ai-stream-director/docker-compose.yml, docs/ARCHITECTURE.md, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/tests/test_runtime_event_pipeline.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_runtime_healthcheck_entrypoints.py, ai-stream-director/tests/test_contracts.py
difficulty: medium
----
## Implementation summary

`TranscriptRouter` now keeps raw transcript messages with preserved start and
end timestamps, while deriving bounded utterance candidates from the current
recent raw history. `get_recent_events()` still returns raw events for audit and
timing checks. New public APIs expose assembled candidates and transcript-shaped
candidate events for the local trigger prefilter.

Candidate assembly starts a new utterance when the stream changes, the
timestamp gap is too large, duration would exceed the configured maximum,
current text ends with `.`, `!`, or `?`, text length would exceed the configured
character limit, or the source event count limit has already been reached.
Candidate text trims raw fragments and joins them with a single space.

Runtime transcript evaluation now classifies assembled candidate events and
uses the newest assembled candidate end timestamp as the prefilter reference
time. The AI director context text is also rendered from assembled candidate
lines, so split events such as `holy` followed by `cow` reach the director as
`player_2: holy cow`. Accepted runtime results still return and log the raw
accepted `TranscriptMessage`.

The new utterance bounds are available through config, Compose, `.env.example`,
and architecture docs:

- `TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS=2.0`
- `TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS=8.0`
- `TRANSCRIPT_UTTERANCE_MAX_CHARACTERS=240`
- `TRANSCRIPT_UTTERANCE_MAX_EVENTS=8`

## Review focus

- Confirm raw timestamp preservation remains correct for live and terminal
  transcript paths.
- Check that candidate source indexes are relative to the currently trimmed
  recent raw history.
- Verify the split rules are applied before adding the overflowing event.
- Confirm duplicate suppression sees repeated assembled utterances rather than
  individual speech-to-text fragments.
- Confirm the lookback clip trigger time comes from the assembled candidate end
  timestamp.
- Confirm AI-disabled and scheduler-gated paths still accept raw messages
  without calling the director.

## Validation

- `python -m unittest tests.test_transcription_event_api tests.test_runtime_event_pipeline tests.test_dry_run_obs tests.test_runtime_healthcheck_entrypoints tests.test_contracts tests.test_transcription_runtime`
- `python -m unittest discover -s tests`

Both commands passed. `python -m unittest discover` from `ai-stream-director/`
ran zero tests unless the `tests` directory was specified explicitly.

## Known gaps

No known implementation gaps. The reviewer should still inspect the prefilter
interaction carefully because the prefilter also builds same-stream context from
the transcript-shaped candidate events it receives.
