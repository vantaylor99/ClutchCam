description: Add structured event logging primitives for orchestration decisions
prereq: production-service-boundaries
files: ai-stream-director/src/services/telemetry.py, ai-stream-director/src/main.py, ai-stream-director/tests/test_telemetry.py, docs/ROADMAP.md
----
The MVP terminal output is readable for humans, but production debugging needs
machine-readable events that explain why the system did or did not switch.

Add a small standard-library-only telemetry seam that can emit structured JSON
events for transcript receipt, prefilter decisions, model escalation, model
decisions, clip requests, and switch actions. The first pass should not replace
the human terminal logger; it should provide a reusable event logger that future
runtime services can call while preserving the MVP's existing console behavior.

TODO:

- Add a lightweight `services.telemetry` module with structured event data and a
  JSON-lines emitter.
- Include timestamp, event name, stream ID when applicable, correlation ID when
  supplied, and detail fields without requiring external logging packages.
- Make the emitter injectable so tests can capture events in memory.
- Add tests for deterministic JSON output, optional fields, and correlation ID
  propagation.
- Add a small integration point in `main.process_line(...)` only if it can be
  done without disrupting the active prefilter ticket; otherwise leave a review
  note that runtime wiring should happen after prefilter lands.
- Run focused tests with bytecode disabled:
  `python -B -m unittest tests.test_telemetry tests.test_dry_run_obs -v`.
