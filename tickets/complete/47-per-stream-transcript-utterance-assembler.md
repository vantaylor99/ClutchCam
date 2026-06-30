description: Group nearby speech from the same player before trigger checks so reactions are judged by what was said, not by speech-to-text chunk boundaries.
prereq: transcript-prefilter-recent-context-boundaries
files: ai-stream-director/src/transcript_router.py, ai-stream-director/src/main.py, ai-stream-director/src/config.py, ai-stream-director/scripts/latency_soak_harness.py, ai-stream-director/.env.example, ai-stream-director/docker-compose.yml, docs/ARCHITECTURE.md, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/tests/test_runtime_event_pipeline.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_runtime_healthcheck_entrypoints.py, ai-stream-director/tests/test_contracts.py
difficulty: medium
----
Implemented and reviewed per-stream transcript utterance assembly before local trigger evaluation.

`TranscriptRouter` now preserves raw transcript messages with start and end timestamps while deriving bounded utterance candidates from current recent raw history. Raw events remain available through `get_recent_events()`, and assembled candidate events are available for local trigger detection and AI prompt context.

Candidate assembly splits when the stream changes, the same-stream timestamp gap exceeds the configured maximum, duration would exceed the configured maximum, the current text ends with `.`, `!`, or `?`, the joined text would exceed the character limit, or the source event count limit has already been reached. Candidate source indexes are relative to the currently trimmed raw history.

Runtime transcript evaluation now passes assembled candidate events into the local trigger prefilter, uses the newest assembled candidate end timestamp for the trigger reference time, and renders AI director context from assembled candidate lines. Terminal input and live transcription events use the same router path. Accepted runtime results still return and log the raw accepted `TranscriptMessage`.

The new config knobs are documented and wired through environment defaults and Compose:

- `TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS=2.0`
- `TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS=8.0`
- `TRANSCRIPT_UTTERANCE_MAX_CHARACTERS=240`
- `TRANSCRIPT_UTTERANCE_MAX_EVENTS=8`

## Review findings

- Checked the implement commit `af6bbbb`, including the router assembly logic, runtime trigger timing, prefilter interaction, config validation, Compose/env/docs wiring, latency harness update, and focused tests.
- Confirmed raw transcript events remain preserved for audit and timing checks while assembled candidates drive prefilter and AI context.
- Confirmed split rules are applied before the overflowing event is added to the current candidate, and source indexes are recalculated after history trimming.
- Confirmed ticket `46`'s prefilter overlap guard still applies with assembled candidate events, so older same-stream context alone does not trigger the newest candidate.
- Confirmed repeated assembled utterances are skipped by phrase-level duplicate suppression within the duplicate window.
- Confirmed AI-disabled and scheduler-gated paths still accept raw transcript messages without calling the AI director.
- The tess review agent initially failed because the child Codex process hit a usage-limit error before doing review work. The review was completed manually from the committed implementation and current tree.
- No inline fixes were required during review. No major findings remain. No backlog, fix, plan, blocked, or tripwire tickets were created.

## Validation

Ran from `ai-stream-director`:

- `python -m unittest tests.test_transcription_event_api tests.test_runtime_event_pipeline tests.test_dry_run_obs tests.test_runtime_healthcheck_entrypoints tests.test_contracts tests.test_transcription_runtime`
  - Result: 105 tests passed.
- `python -m unittest discover -s tests`
  - Result: 299 tests passed.
- `python -m py_compile src/transcript_router.py src/main.py src/config.py scripts/latency_soak_harness.py`
  - Result: passed.

Also ran from the repository root:

- `rg -n "TranscriptMessage\(|\.timestamp|timestamp=" ai-stream-director/src ai-stream-director/tests ai-stream-director/scripts`
  - Result: no stale `TranscriptMessage(timestamp=...)` constructor call sites remain.
- `rg -n "AppConfig\(" ai-stream-director/src ai-stream-director/tests ai-stream-director/scripts`
  - Result: all direct `AppConfig` construction sites include the new utterance fields.
- `git diff --check af6bbbb..HEAD`
  - Result: passed.
