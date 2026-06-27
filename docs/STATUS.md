# Current Project Status

Last updated: 2026-06-27.

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
- OpenAI-compatible Gemma/vLLM provider support through `AI_PROVIDER`,
  `GEMMA_API_URL`, `GEMMA_MODEL`, and optional `GEMMA_API_KEY`.
- Local transcript pre-filtering before expensive model calls.
- Shared production-facing event contracts in `src/contracts.py`.
- Importable production service boundary scaffolding in `src/services/`.
- A first rolling lookback buffer implementation in `src/services/buffer.py`
  with FFmpeg command construction, segment metadata rehydration, retention
  pruning, fixture-mode tests, and local playlist clip resolution.
- A first local RTMP/SRT ingest configuration using SRS through Docker Compose.
  The `media-server` service mounts `ai-stream-director/infra/srs.conf`,
  exposes RTMP, SRT, the SRS HTTP API, and HTTP stream output, and publishes
  stable streams under `live/player_1` through `live/player_4`.
- Runtime entrypoints for the buffer worker and transcription worker.
- Health-check and structured-log primitives for service runtimes.
- Runtime configuration validation for locally-checkable URL, port, stream,
  duration, provider, and path settings.
- Centralized secret redaction for structured health/config-style diagnostic
  details.
- No-player smoke entrypoints under `ai-stream-director/scripts/` for media
  server, buffer worker, transcription API, AI endpoint, and dry-run
  orchestrator checks.
- An opt-in deterministic offline latency/soak harness that exercises the
  transcript-to-buffered-switch path with fake model, buffer, and switch
  adapters and emits structured timing-budget JSON.
- A one-command checkpoint runner that safely skips or runs each smoke boundary
  and emits structured JSON.
- An opt-in generated-ingest checkpoint script that can start or target SRS and
  the buffer worker, publish bounded generated RTMP streams, and verify that a
  lookback clip becomes resolvable on a local Linux host.
- An optional `local-transcription` Compose profile for a local
  Faster-Whisper/OpenAI-compatible transcription server. This profile is
  disabled by default and remains endpoint-contract driven through
  `TRANSCRIPTION_API_URL`.
- An import-safe `RuntimeTranscriptEventHandler` boundary that routes normalized
  `TranscriptEvent` objects through the router, local prefilter, AI director,
  scheduler gates, and buffered switch target construction.
- An OBS media-source switcher adapter that can update a known OBS Media Source
  with a resolved buffered clip URI before cutting to the target scene.
- FFmpeg audio extraction supervision for late or reconnecting live inputs,
  using bounded restart backoff and per-stream isolation.
- Operator runbooks under `docs/runbooks/` for terminal dry-run setup, local
  Linux Compose setup, smoke checks, OBS scene preparation, stream publishing,
  recovery from common local event failures, and Linux/cloud deployment
  topology.

## What Is Partially Started

Production-oriented configuration has been introduced:

- `GEMMA_API_URL`
- `GEMMA_MODEL`
- `GEMMA_API_KEY`
- `TRANSCRIPTION_API_URL`
- `TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS`
- Optional local transcription service settings: `FASTER_WHISPER_IMAGE`,
  `FASTER_WHISPER_BIND_ADDR`, `FASTER_WHISPER_PORT`,
  `FASTER_WHISPER_MODEL`, `FASTER_WHISPER_DEVICE`,
  `FASTER_WHISPER_COMPUTE_TYPE`, and related worker/cache knobs
- `INGEST_API_URL`
- `LOOKBACK_BUFFER_DIR`
- `LOOKBACK_WINDOW_SECONDS`
- `SWITCH_LOOKBACK_SECONDS`
- SRS Docker settings: `SRS_IMAGE`, `SRS_BIND_ADDR`, `SRS_RTMP_PORT`,
  `SRS_HTTP_API_PORT`, `SRS_HTTP_STREAM_PORT`, and `SRS_SRT_PORT`

`OLLAMA_BASE_URL` and `OLLAMA_MODEL` remain compatibility aliases. The native
Ollama provider and OpenAI-compatible provider are both implemented.

For the Docker Compose stack, `INGEST_API_URL` defaults to
`rtmp://media-server:1935/live` so future FFmpeg buffer workers can build
worker-facing URLs without host port assumptions.

The shared contracts currently define:

- `StreamSource`
- `TranscriptEvent`
- `HypeSignal`
- `LookbackClipRequest`
- `SwitcherTarget`, including optional resolved buffered media URI

These contracts are partially wired into service boundaries, but not yet into a
single end-to-end production runtime. Normalized transcript events now have an
orchestrator sink, but the transcription worker is not yet connected to a live
transport into that sink.

The `src/services/` package defines lightweight boundaries for:

- `services.ingestion`: configured `StreamSource` records, source providers, and
  pure RTMP/SRT URL helpers.
- `services.buffer`: `LookbackClipRequest` resolution states plus the first
  segment-based FFmpeg and fixture buffer implementations.
- `services.transcription`: audio input references, extraction configuration,
  fixture audio extraction, FFmpeg audio extraction command/lifecycle helpers,
  a Faster-Whisper-compatible HTTP adapter, and transcript event emitters.
- `services.ai`: transcript or hybrid context to optional `HypeSignal` output.
- `services.switcher`: immediate scene switches, hype-signal-to-buffered-target
  helpers, buffer-backed clip resolution, and ready/pending/rejected switch
  results.

These modules intentionally do not instantiate OBS, FFmpeg, media-server,
transcription, AI, Docker, or network clients at import time. The concrete
buffer adapter starts FFmpeg only after explicit construction and `start()`.
`get_config()` now validates locally-checkable production-facing values before
long-running services start, while keeping dry-run and keyless local endpoint
workflows available.

## What Does Not Exist Yet

The repo does not yet include:

- A single end-to-end runtime that starts media ingest, FFmpeg buffering, audio
  extraction, transcription, AI orchestration, and switching together.
- Configuration/runtime wiring that injects the OBS media-source adapter into a
  full production path by default.
- A completed live Docker/Linux validation run that includes real
  Faster-Whisper transcription and OBS playback. Live generated-ingest
  validation against SRS, FFmpeg, the rolling buffer, Ollama, and the dry-run
  orchestrator has passed on `clutchcam-media-1`; evidence is recorded in
  `tickets/complete/43-linux-generated-ingest-acceptance.md`. Deterministic
  reconnect proof also passed on `clutchcam-media-1`; evidence is recorded in
  `tickets/complete/43.5-buffer-reconnect-telemetry-proof.md`.
- PyVMIX media-source playback that consumes a resolved buffered clip URI.
- End-to-end tests using sample media fixtures.
- Live latency/soak runs against real LAN or cloud endpoints. The offline
  harness exists as a deterministic baseline.
- Live cloud or multi-host deployment validation. The topology runbook now
  documents intended host-local, two-Linux-host, and future cloud GPU/VM
  layouts, but those paths have not been exercised with real remote services.

## Validation

The current Python unit suite covers the existing MVP boundaries and production
service scaffolding. Run it from `ai-stream-director/`:

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

The buffered switcher tests run without OBS, PyVMIX, FFmpeg, Docker, or real
media:

```powershell
python -m unittest tests.test_buffered_switcher -v
```

The local ingest configuration tests run without Docker, FFmpeg, or network
sockets:

```powershell
python -m unittest tests.test_ingestion_config -v
```

The transcription adapter tests mock the Faster-Whisper HTTP surface and run
without network access:

```powershell
python -m unittest tests.test_transcription_event_api -v
```

The runtime transcript event boundary tests run without live FFmpeg, OBS,
Docker, or AI services:

```powershell
python -m unittest tests.test_runtime_event_pipeline -v
```

The generated-ingest checkpoint defaults to a safe skipped JSON report. Tickets
40-43 have landed, and the live form has passed on Linux with Docker Engine,
the Compose plugin, host FFmpeg, SRS, and the rolling buffer:

```powershell
python scripts\compose_generated_ingest_checkpoint.py
python scripts\compose_generated_ingest_checkpoint.py --run
python scripts\compose_generated_ingest_checkpoint.py --run --streams player_1,player_2,player_3,player_4
python scripts\compose_generated_ingest_checkpoint.py --run --streams player_1 --reconnect-proof
```

When multiple streams are requested, the checkpoint now requires every
requested stream to resolve a clip; a single ready stream no longer satisfies a
multi-stream run. The optional reconnect proof runs a second bounded publish
and requires stable `buffer-worker` identity plus latest segment sequence
advancement.

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
