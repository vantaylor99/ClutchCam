description: Completed structured event logging primitives for orchestration decisions
prereq: production-service-boundaries
files: ai-stream-director/src/services/telemetry.py, ai-stream-director/src/services/__init__.py, ai-stream-director/tests/test_telemetry.py, ai-stream-director/tests/test_service_boundaries.py
----
Structured event logging primitives are ready for future orchestration runtime
wiring.

Built:

- Added `services.telemetry` as a standard-library-only service module.
- Added `TelemetryEvent` for timestamped event records with event name, optional
  stream ID, optional correlation ID, and structured detail fields.
- Added deterministic JSON-lines serialization through
  `TelemetryEvent.to_json_line()` using compact sorted-key JSON and strict JSON
  numeric handling.
- Added `JsonLinesTelemetryEmitter` with injectable callable or file-like sinks
  so tests and future runtimes can capture or redirect events.
- Added `TelemetryLogger` with injectable emitter and clock for timestamped
  event creation and deterministic tests.
- Added stable event-name constants for transcript receipt, prefilter decisions,
  model escalation, model decisions, clip requests, and switch actions.
- Added `services.telemetry` to the service package export list and import
  boundary test.

Runtime wiring note:

- `main.py` was intentionally left untouched in this pass. Runtime wiring should
  happen around transcript acceptance, prefilter outcomes, model escalation,
  model decisions, clip requests, and switch actions after the worker and
  buffered-switching call sites settle.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_telemetry tests.test_service_boundaries -v
```

Result:

- Focused telemetry/service-boundary suite: 16 tests passed.
