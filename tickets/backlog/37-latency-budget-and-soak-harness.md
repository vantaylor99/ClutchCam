description: Add latency budget and soak-test harness for live orchestration
prereq: runtime-event-pipeline-wiring, compose-generated-ingest-checkpoint, obs-buffered-media-source-adapter
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/scripts/, ai-stream-director/tests/
----
The production system needs more than unit correctness: it must stay responsive
under a live-event workload. After transcript-driven buffered switching and the
generated-ingest checkpoint exist, add a bounded latency and soak harness that
can measure end-to-end timing without requiring a real event.

Expected behavior:

- Define target latency budgets for ingest, buffer segment availability,
  transcription, local prefilter, model call, clip resolution, and switch action.
- Add a synthetic workload that can run for a bounded duration and report timing
  distributions, dropped/late events, memory growth, and process failures.
- Keep the soak harness opt-in and out of the default unit suite.
- Make the output useful for local Linux and cloud/remote AI comparisons.
- Document how to interpret failures and when a run is too slow for live use.
