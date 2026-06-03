description: Define production service package boundaries and interfaces
prereq:
files: README.md, docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/src/services/__init__.py, ai-stream-director/src/services/ingestion.py, ai-stream-director/src/services/buffer.py, ai-stream-director/src/services/transcription.py, ai-stream-director/src/services/ai.py, ai-stream-director/src/services/switcher.py, ai-stream-director/tests/test_service_boundaries.py
----
Completed review of the production service boundary scaffolding.

The `ai-stream-director/src/services/` package now defines import-safe,
standard-library-only boundaries for the next production services while leaving
the terminal-driven OBS MVP workflow unchanged:

- `services.ingestion`: stable `StreamSource` records through
  `StreamSourceProvider`, `StaticStreamSourceProvider`, and
  `build_configured_sources(...)`.
- `services.buffer`: `LookbackBuffer`, `ClipResolution`, and
  `ClipResolutionStatus` for ready, pending, or unavailable lookback requests.
- `services.transcription`: `AudioInputRef` and `Transcriber` for
  `TranscriptEvent` emission.
- `services.ai`: `HypeContext` and `HypeClassifier` for optional `HypeSignal`
  output.
- `services.switcher`: `OutputSwitcher`, `SwitchResult`, and `SwitchStatus` for
  immediate or future buffered switching via `SwitcherTarget`.

Review notes:

- The boundary names and result/status shapes are sufficient for the dependent
  `rolling-lookback-buffer` and `local-media-server-ingest` implement tickets.
  Those tickets can add concrete adapters and narrowly extend results, such as
  buffer segment details, without replacing the current contracts.
- The service modules import only the standard library plus local `config` and
  `contracts` modules. They do not import OBS controllers, FFmpeg/GStreamer
  code, media-server code, Faster-Whisper clients, AI runtime clients, Docker
  helpers, `requests`, or terminal MVP runtime modules.
- README and architecture/status/roadmap docs now describe the boundary package
  as scaffold-only and keep concrete media ingest, rolling buffer,
  transcription, AI adapter, and buffered switching behavior in follow-up work.

Validation:

- Passed: `python -m unittest discover -s tests -p "test_service_boundaries.py" -v`
  from `ai-stream-director/` (7 tests).
- Attempted: `python -m unittest discover -s tests -v` from
  `ai-stream-director/`. The service-boundary and contract tests executed, but
  the full suite failed during existing MVP test imports because this Python
  environment does not have `requests` installed.
- Confirmed missing local dependencies with `python -m pip show requests` and
  `python -m pip show obsws-python`; both packages are absent in this
  environment.

Usage notes:

- Future ingestion adapters should implement `StreamSourceProvider` and can use
  `build_configured_sources("rtmp://media-server:1935/live")` or another base
  URL to produce stable `player_1` through `player_4` source records.
- Future buffer adapters should implement `LookbackBuffer.resolve_clip(...)`
  and return `ClipResolution.ready(...)`, `pending(...)`, or
  `unavailable(...)` without making callers inspect FFmpeg or filesystem
  details directly.
- Re-run `python -m unittest discover -s tests -v` after installing
  `ai-stream-director/requirements.txt` in the validation environment.
