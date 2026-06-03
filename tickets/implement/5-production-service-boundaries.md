description: Define production service package boundaries and interfaces
prereq:
files: README.md, docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/src/contracts.py, ai-stream-director/src/config.py, ai-stream-director/src/services/__init__.py, ai-stream-director/src/services/ingestion.py, ai-stream-director/src/services/buffer.py, ai-stream-director/src/services/transcription.py, ai-stream-director/src/services/ai.py, ai-stream-director/src/services/switcher.py, ai-stream-director/tests/test_service_boundaries.py
----
Create the production service boundary scaffolding that future ingestion,
buffer, transcription, AI orchestration, and switching implementations will
plug into. This work should not replace the current terminal-driven OBS MVP or
change its command-line workflow. The existing app under `ai-stream-director/src`
must still run with its current top-level modules and dry-run OBS mode.

The package layout should add importable boundary modules under
`ai-stream-director/src/services/`:

```text
ai-stream-director/src/
  contracts.py               # shared event/request/target dataclasses
  config.py                  # environment-driven production defaults
  services/
    __init__.py
    ingestion.py             # stream source discovery / ingest boundary
    buffer.py                # rolling lookback buffer boundary
    transcription.py         # speech-to-text boundary
    ai.py                    # hype classification / model boundary
    switcher.py              # output switching boundary
```

`contracts.py` remains the shared vocabulary for cross-service payloads. The
current contracts already include `StreamSource`, `TranscriptEvent`,
`HypeSignal`, `LookbackClipRequest`, and `SwitcherTarget`; extend this file only
when an interface needs an implementation-neutral payload shared across more
than one service. Provider-specific response shapes, FFmpeg process state, OBS
client objects, and Faster-Whisper response JSON should stay outside these
contracts.

Each service module should define a small implementation-neutral interface using
Python standard library types (`Protocol`, dataclasses, or simple exceptions are
fine). These boundaries should be importable without OBS, FFmpeg, media inputs,
Ollama/Gemma, Faster-Whisper, Docker, or network access.

Suggested interface responsibilities:

- `services.ingestion`: expose configured `StreamSource` records or a protocol
  for listing active sources by stable stream IDs (`player_1` through
  `player_4`). Do not start a media server in this module.
- `services.buffer`: accept a `LookbackClipRequest` and describe the resolved
  playable media range or a pending/unavailable result. Do not launch FFmpeg in
  this ticket.
- `services.transcription`: accept stream/audio input references and emit
  `TranscriptEvent` objects. Do not call Faster-Whisper in this ticket.
- `services.ai`: accept transcript/hybrid context and return `HypeSignal`
  objects or no signal. The interface must not assume local Docker, local host
  processes, or remote GPU inference.
- `services.switcher`: accept a `SwitcherTarget` and expose the output switch
  operation. Keep immediate OBS switching and future buffered playback behind
  the same boundary.

Documentation should explain that these modules are boundaries, not running
services yet. The architecture and roadmap should make clear that follow-up
tickets such as `rolling-lookback-buffer` and `local-media-server-ingest`
implement behavior behind these interfaces.

Validation should prove the scaffolding is lightweight:

- Importing all `services.*` modules succeeds in a plain unit test process.
- Import tests do not instantiate OBS clients, FFmpeg subprocesses, media
  servers, AI clients, or transcription clients.
- Existing MVP tests still pass from `ai-stream-director/` with:

```powershell
python -m unittest discover -s tests -v
```

TODO:
- Add the `ai-stream-director/src/services/` package and boundary modules.
- Define minimal protocols/dataclasses/exceptions for ingestion, buffer,
  transcription, AI, and switcher boundaries using existing contracts wherever
  possible.
- Keep all production service configuration environment-driven through
  `config.py`; avoid hardcoded host paths except documented defaults such as
  `/dev/shm/clutchcam`.
- Update `README.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`,
  `docs/STATUS.md`, and `ai-stream-director/README.md` to document the package
  layout and clarify that the MVP remains runnable.
- Add focused unit tests in `ai-stream-director/tests/test_service_boundaries.py`
  for importability and contract-only boundaries.
- Run the full Python unit suite and record any skipped external validation in
  the review ticket.
