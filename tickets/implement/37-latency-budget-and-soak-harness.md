description: Add latency budget and soak-test harness for live orchestration
prereq: runtime-event-pipeline-wiring, compose-generated-ingest-checkpoint, obs-buffered-media-source-adapter
files: ai-stream-director/scripts/, ai-stream-director/tests/, docs/ARCHITECTURE.md, docs/ROADMAP.md
----
The production system needs more than unit correctness: it must stay responsive
under live-event workload. Add an opt-in synthetic latency and soak harness that
can run without a real event, Docker, OBS, GPUs, or live network services by
default.

The harness should exercise the production contracts rather than the terminal
prompt loop. It should make timing budgets visible for ingest/buffer
availability, transcription event handling, local prefilter, model decision,
clip resolution, and switch action. It should produce structured JSON that can
be compared between a local-only run and later LAN/cloud endpoint runs.

The first implementation may use deterministic fake components for model,
buffer, and switcher timing. Live infrastructure should stay opt-in behind
explicit flags or environment values, and the default unit suite must remain
fast.

TODO:

- Define default latency budget constants for the major live path stages.
- Add an opt-in script under `ai-stream-director/scripts/` that runs a bounded
  synthetic workload and emits structured JSON.
- Report event count, accepted/rejected events, late/dropped events, per-stage
  timing distributions, max/average timing, basic memory/process health where
  feasible, and budget pass/fail status.
- Keep the default run deterministic and offline.
- Add unit tests for JSON shape, budget failures, bounded duration/event count,
  and deterministic fake component behavior.
- Document how to run the harness and interpret failures in architecture or
  roadmap docs.
