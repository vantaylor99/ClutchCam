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

## What Is Partially Started

Production-oriented configuration has been introduced:

- `GEMMA_API_URL`
- `GEMMA_MODEL`
- `TRANSCRIPTION_API_URL`
- `INGEST_API_URL`
- `LOOKBACK_BUFFER_DIR`
- `LOOKBACK_WINDOW_SECONDS`
- `SWITCH_LOOKBACK_SECONDS`

`OLLAMA_BASE_URL` and `OLLAMA_MODEL` remain compatibility aliases while the MVP
still talks to Ollama's native API shape.

The shared contracts currently define:

- `StreamSource`
- `TranscriptEvent`
- `HypeSignal`
- `LookbackClipRequest`
- `SwitcherTarget`

These contracts are not yet wired into full production services.

The `src/services/` package defines lightweight boundaries for:

- `services.ingestion`: configured `StreamSource` records and source providers.
- `services.buffer`: `LookbackClipRequest` resolution states.
- `services.transcription`: audio input references and transcript event emitters.
- `services.ai`: transcript or hybrid context to optional `HypeSignal` output.
- `services.switcher`: immediate or buffered output switch requests.

These modules intentionally do not instantiate OBS, FFmpeg, media-server,
transcription, AI, Docker, or network clients.

## What Does Not Exist Yet

The repo does not yet include:

- A local RTMP/SRT media server configuration.
- FFmpeg or GStreamer processes for stream ingest and segmenting.
- A rolling `/dev/shm` circular buffer implementation.
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

## Known Repo Notes

Tess is already installed in `tess/`. Ticket stage folders were originally
ignored by `tickets/.gitignore`; new shared-roadmap tickets should be tracked so
the project plan moves with the repo.

`tickets/.in-progress` may contain stale local runner state after interrupted
or manually completed Tess runs. It is ignored metadata and can be cleared before
running Tess again if it points at a ticket that no longer exists.
