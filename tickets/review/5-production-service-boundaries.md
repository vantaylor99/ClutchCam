description: Define production service package boundaries and interfaces
prereq:
files: README.md, docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/src/services/__init__.py, ai-stream-director/src/services/ingestion.py, ai-stream-director/src/services/buffer.py, ai-stream-director/src/services/transcription.py, ai-stream-director/src/services/ai.py, ai-stream-director/src/services/switcher.py, ai-stream-director/tests/test_service_boundaries.py
----
Implemented lightweight production service boundary scaffolding without changing
the current terminal-driven OBS MVP workflow.

The new `ai-stream-director/src/services/` package is importable from the
existing top-level `src` module path and contains standard-library-only
boundaries:

- `services.ingestion`: `StreamSourceProvider`, `StaticStreamSourceProvider`,
  and `build_configured_sources(...)` for stable `player_1` through `player_4`
  source records.
- `services.buffer`: `LookbackBuffer`, `ClipResolution`, and
  `ClipResolutionStatus` for ready, pending, or unavailable lookback media
  ranges.
- `services.transcription`: `AudioInputRef` and `Transcriber` for emitting
  `TranscriptEvent` values from stream/audio references.
- `services.ai`: `HypeContext` and `HypeClassifier` for optional `HypeSignal`
  output from transcript or hybrid context.
- `services.switcher`: `OutputSwitcher`, `SwitchResult`, and `SwitchStatus` for
  immediate or future buffered output switching through `SwitcherTarget`.

No service module imports OBS controllers, FFmpeg/GStreamer code, media-server
code, Faster-Whisper clients, AI runtime clients, Docker helpers, `requests`, or
the terminal MVP runtime modules.

Documentation updates:

- Root `README.md` now lists the boundary package as current scaffolding and
  clarifies that follow-up tickets implement behavior behind it.
- `docs/ARCHITECTURE.md` includes the package layout, import-safety rule, and
  per-service scaffold descriptions.
- `docs/ROADMAP.md` marks the boundary layout as present and keeps rolling
  lookback buffer and local media-server ingest as follow-up work.
- `docs/STATUS.md` records the new boundary package and dependency expectations
  for full validation.
- `ai-stream-director/README.md` shows the `src/services/` layout and states
  that these modules are protocols/dataclasses only.

Validation performed:

- Passed: `python -m unittest discover -s tests -p "test_service_boundaries.py" -v`
  from `ai-stream-director/` (7 tests).
- Passed: `python -m unittest tests.test_service_boundaries -v` from
  `ai-stream-director/` (7 tests).
- Attempted: `python -m unittest discover -s tests -v` from
  `ai-stream-director/`. The new service-boundary tests passed, but the full
  suite failed during existing MVP test import because this Python environment
  does not have `requests` installed.
- Attempted: `python -m pip install -r requirements.txt` from
  `ai-stream-director/`. Installation was blocked by restricted network access
  (`WinError 10013`), so `obsws-python` and `requests` could not be installed for
  full-suite validation.

Review focus:

- Confirm the boundary names and result/status shapes are sufficient for the
  follow-up `rolling-lookback-buffer` and `local-media-server-ingest` tickets.
- Re-run `python -m unittest discover -s tests -v` in an environment with
  `requirements.txt` installed.
