# Current Project Status

Last updated: 2026-06-03.

## What Exists

`ai-stream-director/` is a working local MVP for AI-assisted OBS scene switching.
The app starts from `src/main.py`, loads environment configuration from
`src/config.py`, keeps transcript history through `src/transcript_router.py`,
asks `src/ai_director.py` for JSON scene decisions, and applies switching rules
through `src/scheduler.py` and `src/obs_controller.py`.

The MVP supports:

- OBS WebSocket control with required scene-name validation.
- `DRY_RUN_OBS=true` mode for testing without OBS.
- Manual terminal commands such as `/quad`, `/p1`, `/ai off`, and `/status`.
- Non-blocking terminal input so scheduler timers keep advancing.
- Ollama readiness checks and hardened JSON parsing for local model output.
- Shared production-facing event contracts in `src/contracts.py`.
- Importable production service boundary scaffolding in `src/services/`.
- A first rolling lookback buffer implementation in `src/services/buffer.py`
  with FFmpeg command construction, segment metadata rehydration, retention
  pruning, fixture-mode tests, and local playlist clip resolution.
- A first local RTMP/SRT ingest configuration using SRS through Docker Compose.
  The `media-server` service mounts `ai-stream-director/infra/srs.conf`,
  exposes RTMP, SRT, the SRS HTTP API, and HTTP stream output, and publishes
  stable streams under `live/player_1` through `live/player_4`.

## What Is Partially Started

Production-oriented configuration has been introduced:

- `GEMMA_API_URL`
- `GEMMA_MODEL`
- `TRANSCRIPTION_API_URL`
- `INGEST_API_URL`
- `LOOKBACK_BUFFER_DIR`
- `LOOKBACK_WINDOW_SECONDS`
- `SWITCH_LOOKBACK_SECONDS`
- SRS Docker settings: `SRS_IMAGE`, `SRS_BIND_ADDR`, `SRS_RTMP_PORT`,
  `SRS_HTTP_API_PORT`, `SRS_HTTP_STREAM_PORT`, and `SRS_SRT_PORT`

`OLLAMA_BASE_URL` and `OLLAMA_MODEL` remain compatibility aliases while the MVP
still talks to Ollama's native API shape.

For the Docker Compose stack, `INGEST_API_URL` defaults to
`rtmp://media-server:1935/live` so future FFmpeg buffer workers can build
worker-facing URLs without host port assumptions.

The shared contracts currently define:

- `StreamSource`
- `TranscriptEvent`
- `HypeSignal`
- `LookbackClipRequest`
- `SwitcherTarget`

These contracts are not yet wired into full production services.

The `src/services/` package defines lightweight boundaries for:

- `services.ingestion`: configured `StreamSource` records, source providers, and
  pure RTMP/SRT URL helpers.
- `services.buffer`: `LookbackClipRequest` resolution states plus the first
  segment-based FFmpeg and fixture buffer implementations.
- `services.transcription`: audio input references and transcript event emitters.
- `services.ai`: transcript or hybrid context to optional `HypeSignal` output.
- `services.switcher`: immediate or buffered output switch requests.

These modules intentionally do not instantiate OBS, FFmpeg, media-server,
transcription, AI, Docker, or network clients at import time. The concrete
buffer adapter starts FFmpeg only after explicit construction and `start()`.

## What Does Not Exist Yet

The repo does not yet include:

- A wired runtime path that starts FFmpeg lookback buffering as part of the app.
- Faster-Whisper audio extraction or transcription adapter code.
- OpenAI-compatible Gemma/vLLM client support.
- Buffered clip playback through OBS or PyVMIX.
- End-to-end tests using sample media fixtures.
- Production observability, health checks, or deployment documentation.

## Validation

The current Python unit suite covers the existing MVP boundaries and the new
contract/config scaffolding. Run it from `ai-stream-director/`:

```powershell
python -m unittest discover -s tests -v
```

The service-boundary tests include a clean-process import check to prove
`services.*` modules do not pull in runtime client dependencies. Full-suite
validation requires the dependencies in `requirements.txt`, including
`requests` and `obsws-python`.

The rolling-buffer fixture tests run without live media input or FFmpeg:

```powershell
python -m unittest tests.test_rolling_buffer -v
```

The local ingest configuration tests run without Docker, FFmpeg, or network
sockets:

```powershell
python -m unittest tests.test_ingestion_config -v
```

Final terminal-MVP dry-run review passed for calm transcript input, a focused
player moment, cooldown rejection, manual overrides, `/ai off`, `/ai on`,
`/status`, `/quit`, and automatic return to `Quad View`. A live OBS WebSocket
trial still requires OBS to be available with the five documented scenes.

## Known Repo Notes

Tess is already installed in `tess/`. Ticket stage folders were originally
ignored by `tickets/.gitignore`; new shared-roadmap tickets should be tracked so
the project plan moves with the repo.

`tickets/.in-progress` may contain stale local runner state after interrupted
or manually completed Tess runs. It is ignored metadata and can be cleared before
running Tess again if it points at a ticket that no longer exists.
