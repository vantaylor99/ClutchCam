description: Completed latency budget and soak-test harness for live orchestration
prereq: runtime-event-pipeline-wiring, compose-generated-ingest-checkpoint, obs-buffered-media-source-adapter
files: ai-stream-director/scripts/latency_soak_harness.py, ai-stream-director/tests/test_latency_soak_harness.py, docs/ARCHITECTURE.md, docs/ROADMAP.md
----
Implemented an opt-in deterministic offline latency and soak harness for the
live orchestration path.

What changed:

- Added `ai-stream-director/scripts/latency_soak_harness.py`.
- Added deterministic fake model, buffer, and switch adapters that exercise
  production contracts without Docker, OBS, FFmpeg, GPUs, or network services.
- Defined default latency budgets for buffer availability, transcript event
  handling, local prefilter, model decision, clip resolution, switch action, and
  end-to-end handling.
- Emitted structured JSON with event counts, dropped/late counts, per-stage
  timing distributions, budget pass/fail results, event summaries, and basic
  process/memory details.
- Added focused unit tests for report shape, determinism, budget failure exit
  behavior, bounded event counts, and invalid options.
- Documented run and interpretation guidance in architecture docs.

Validation:

- `C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B -m unittest tests.test_latency_soak_harness tests.test_runtime_event_pipeline -v`
- `C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B scripts\latency_soak_harness.py --events 8 --indent 0`
- Full suite later passed with 226 tests.

Notes:

- The default budgets are an offline baseline. Future LAN/cloud comparisons
  should keep the same JSON shape and add live adapters only behind explicit
  opt-in flags.
