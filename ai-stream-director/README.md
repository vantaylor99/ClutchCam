# AI Stream Director MVP

This is a local MVP for an AI-powered OBS stream director.

It does four things:

1. Connects to manually created OBS scenes through OBS WebSocket.
2. Accepts fake transcript lines for 4 players in the terminal.
3. Sends recent transcript context to local Ollama or an OpenAI-compatible AI
   endpoint.
4. Switches OBS scenes when the AI finds a clear focus moment.

It does not create OBS scenes or enable OBS media-source mutation by default.
Local SRS ingest, rolling FFmpeg lookback buffering, audio extraction,
Faster-Whisper HTTP transcription, runtime workers, and buffer-backed switch
resolution now exist behind service boundaries and Compose profiles. The
default prompt still accepts typed transcript lines, while
`LIVE_TRANSCRIPTION_ENABLED=true` lets the orchestrator consume final live
`TranscriptEvent` values from the in-process transcription source.

## Production Direction

The MVP is being shaped into the ClutchCam live media orchestration stack:

1. Local RTMP/SRT ingestion keeps raw live media on the local network.
2. FFmpeg or GStreamer writes each feed into a rolling `/dev/shm` lookback buffer.
3. Faster-Whisper emits timestamped transcript events per stream.
4. Local rules and Gemma classify hype moments through environment-configured APIs.
5. OBS or PyVMIX switches the master output using buffered media from before the trigger.

The production architecture notes live in `../docs/ARCHITECTURE.md`. Shared event contracts for transcripts, hype signals, buffered clip requests, and switcher targets live in `src/contracts.py`.

The `src/services/` package defines the production boundaries for ingestion,
buffering, transcription, AI classification, and switching. These modules stay
import-safe: importing them does not start media servers, FFmpeg,
Faster-Whisper, AI clients, Docker, network calls, or OBS connections.

`src/services/switcher.py` can now turn a stream-focused hype signal into a
`LookbackClipRequest`, resolve it against a lookback buffer, and expose the
ready buffered media URI on a `SwitcherTarget`. The OBS media-source adapter can
update a known OBS media source with that URI before performing the program cut.

Operator runbooks for event setup, smoke checks, and recovery live in
`../docs/runbooks/README.md`. Use them for the terminal dry-run MVP and the
local Linux Compose stack.

## Project Structure

```text
ai-stream-director/
  src/
    contracts.py
    config.py
    services/
      __init__.py
      ingestion.py
      buffer.py
      transcription.py
      ai.py
      switcher.py
    main.py
    obs_controller.py
    ai_director.py
    transcript_router.py
    scheduler.py
  scripts/
    smoke_media_server.py
    smoke_buffer_worker.py
    smoke_transcription_api.py
    smoke_ai_endpoint.py
    smoke_orchestrator_dry_run.py
  docker-compose.yml
  Dockerfile
  infra/
    srs.conf
  requirements.txt
  README.md
  .env.example
```

## Expected OBS Scenes

Create these scenes manually in OBS before running the app:

- `Quad View`
- `Player 1 Fullscreen`
- `Player 2 Fullscreen`
- `Player 3 Fullscreen`
- `Player 4 Fullscreen`

The scene names must match exactly.

On startup, the app connects to OBS WebSocket and validates that all required
scenes exist before the scheduler starts. If any scene is missing or misspelled,
startup exits with a list of the missing scene names. `DRY_RUN_OBS=true` skips
this real OBS validation for local smoke testing.

For buffered playback, create one OBS Media Source that is present in the
fullscreen playback scenes you plan to cut to. Use the source name you pass to
the media-source switcher, for example `ClutchCam Buffered Playback`. The
adapter updates the source with the resolved clip URI and reads the source
settings back before cutting to the target scene. File-backed clips must be
reachable from the machine running OBS at the same path; URL-backed clips are
applied as network media input.

## OBS WebSocket Setup

OBS 28+ includes OBS WebSocket by default.

1. Open OBS.
2. Go to `Tools > WebSocket Server Settings`.
3. Enable the WebSocket server.
4. Keep the port as `4455`, or update `OBS_PORT` in `.env`.
5. Set a password, or leave it blank for local testing.
6. Put that password in `.env` as `OBS_PASSWORD`.

If you are running the Python app in Docker Desktop on Windows or macOS, `OBS_HOST=host.docker.internal` should work. If you run the app directly on your machine without Docker, use `OBS_HOST=127.0.0.1`.

## Setup

From this directory:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set your OBS password:

```text
OBS_PASSWORD=your-obs-websocket-password
```

To test without OBS, enable dry-run mode:

```text
DRY_RUN_OBS=true
```

Dry-run mode skips the OBS WebSocket connection and prints scene switches to the terminal instead. It does not import or require `obsws-python`; real OBS mode requires that dependency and fails clearly if it is missing.

The default Ollama model is:

```text
GEMMA_MODEL=gemma3:4b
GEMMA_API_URL=http://ollama:11434
OLLAMA_MODEL=gemma3:4b
OLLAMA_BASE_URL=http://ollama:11434
```

`GEMMA_*` names are preferred for the production architecture. `OLLAMA_*` names remain compatibility aliases for the current MVP. You can replace the model with another small local Gemma-compatible model if needed.

For local readiness checkpoints, keep the default text-only loop until a future
vision/keyframe ticket opts in to multimodal analysis. Optional later Ollama
Gemma model tags can be used when they are installed locally and supported by
the selected provider, but changing `GEMMA_MODEL` alone does not make visual
analysis part of the near-term checkpoint.

## Local Media Server

Docker Compose includes a local SRS service named `media-server` for RTMP and
SRT ingest. It uses `infra/srs.conf`, listens inside the Compose network on
RTMP `1935/tcp`, HTTP API `1985/tcp`, HTTP stream output `8080/tcp`, and SRT
`10080/udp`, and publishes stable streams under the `live` app.

For the first smoke test, install Docker or Docker Desktop and confirm the
`docker` command is available on `PATH`. From `ai-stream-director/`:

```powershell
docker --version
docker compose version
docker compose up -d media-server
```

Before calling the SRS HTTP API, verify that the host API port is listening:

```powershell
Test-NetConnection 127.0.0.1 -Port 1985
```

The PowerShell check should report `TcpTestSucceeded : True`. On Linux, an
equivalent listener check is:

```bash
ss -ltn '( sport = :1985 )'
```

Then call the SRS summaries endpoint from the host:

```powershell
Invoke-RestMethod http://127.0.0.1:1985/api/v1/summaries
```

If a browser, `Invoke-RestMethod`, or another client reports connection
refused, SRS is not started, Docker is unavailable, or the host port is not
listening. A response from `/api/v1/summaries` means the SRS HTTP API is
reachable, even when no player streams are currently publishing.

Start only the media server on later runs with the same Compose service:

```powershell
docker compose up -d media-server
```

The default host bindings are local-only:

```text
SRS_BIND_ADDR=127.0.0.1
SRS_RTMP_PORT=1935
SRS_HTTP_API_PORT=1985
SRS_HTTP_STREAM_PORT=8080
SRS_SRT_PORT=10080
```

For same-machine smoke tests, use localhost, preferably the explicit
`127.0.0.1` URL shown above. If publishers or operators are on another machine,
use the Linux server's LAN IP in publish and playback URLs. Set
`SRS_BIND_ADDR=0.0.0.0` only when that LAN exposure and the machine's firewall
boundary are intentional. Player capture machines cannot reach a host-local
`127.0.0.1` binding from another computer.

For OBS or vMix RTMP publishing, use this server/app shape and a per-player
stream key:

```text
Server: rtmp://<media-server-host>:<SRS_RTMP_PORT>/live
Stream key: player_1
```

Equivalent full RTMP publish URLs are:

```text
rtmp://<media-server-host>:<SRS_RTMP_PORT>/live/player_1
rtmp://<media-server-host>:<SRS_RTMP_PORT>/live/player_2
rtmp://<media-server-host>:<SRS_RTMP_PORT>/live/player_3
rtmp://<media-server-host>:<SRS_RTMP_PORT>/live/player_4
```

SRT publishers should use explicit publish-mode stream IDs:

```text
srt://<media-server-host>:<SRS_SRT_PORT>?streamid=#!::r=live/player_1,m=publish
srt://<media-server-host>:<SRS_SRT_PORT>?streamid=#!::r=live/player_2,m=publish
srt://<media-server-host>:<SRS_SRT_PORT>?streamid=#!::r=live/player_3,m=publish
srt://<media-server-host>:<SRS_SRT_PORT>?streamid=#!::r=live/player_4,m=publish
```

Inside Docker Compose, workers should consume service-DNS URLs rather than host
ports:

```text
INGEST_API_URL=rtmp://media-server:1935/live
rtmp://media-server:1935/live/player_1
rtmp://media-server:1935/live/player_2
rtmp://media-server:1935/live/player_3
rtmp://media-server:1935/live/player_4
```

If a worker needs SRT request/play URLs, use explicit request mode:

```text
srt://media-server:10080?streamid=#!::r=live/player_1,m=request
```

Repeat that pattern for `player_2`, `player_3`, and `player_4`.

The upstream `ossrs/srs:6` image does not guarantee `curl` or `wget` for an
in-container health check, so Compose keeps the endpoint available and uses
manual host validation:

```powershell
Invoke-RestMethod http://127.0.0.1:1985/api/v1/summaries
```

### Generated-Source Smoke Tests

Publish a generated RTMP source for `player_1`:

```powershell
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 -f lavfi -i sine=frequency=440 -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -c:a aac -f flv rtmp://127.0.0.1:1935/live/player_1
```

Publish a generated SRT source for `player_1`:

```powershell
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 -f lavfi -i sine=frequency=440 -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -c:a aac -pes_payload_size 0 -f mpegts "srt://127.0.0.1:10080?streamid=#!::r=live/player_1,m=publish"
```

Validate the stream with local tools:

```powershell
ffprobe -hide_banner rtmp://127.0.0.1:1935/live/player_1
ffplay rtmp://127.0.0.1:1935/live/player_1
ffplay "srt://127.0.0.1:10080?streamid=#!::r=live/player_1,m=request"
ffplay http://127.0.0.1:8080/live/player_1.flv
Invoke-RestMethod http://127.0.0.1:1985/api/v1/summaries
```

To run four distinguishable test feeds, repeat the publish command for
`player_2`, `player_3`, and `player_4`. Use different audio frequencies such as
`550`, `660`, and `770`, and change the test pattern if useful, for example
`testsrc2` or `smptebars`.

## Rolling Lookback Buffer

`src/services/buffer.py` includes a segment-based lookback buffer implementation
for stable stream IDs `player_1` through `player_4`.

- `FixtureLookbackBuffer` resolves synthetic `SegmentRecord` values for
  deterministic tests and dry-run validation without FFmpeg.
- `FFmpegRollingLookbackBuffer` builds one FFmpeg segment-muxer command per
  stream and writes `.ts` segments plus `segments.csv` metadata under
  `<LOOKBACK_BUFFER_DIR>/<stream_id>/`.
- `resolve_clip()` returns `ready`, `pending`, or `unavailable`. Ready results
  include a generated local playlist URI and the exact segment file URIs used.

Runtime settings:

```text
LOOKBACK_BUFFER_DIR=/dev/shm/clutchcam
LOOKBACK_WINDOW_SECONDS=30
SWITCH_LOOKBACK_SECONDS=15
LOOKBACK_SEGMENT_SECONDS=2
FFMPEG_EXECUTABLE=ffmpeg
INGEST_API_URL=rtmp://media-server:1935/live
LOOKBACK_INPUT_URL_PLAYER_1=rtmp://media-server:1935/live/player_1
LOOKBACK_INPUT_URL_PLAYER_2=rtmp://media-server:1935/live/player_2
LOOKBACK_INPUT_URL_PLAYER_3=rtmp://media-server:1935/live/player_3
LOOKBACK_INPUT_URL_PLAYER_4=rtmp://media-server:1935/live/player_4
```

If a per-player input URL is not set, it defaults to
`<INGEST_API_URL>/<stream_id>`. On Linux, keep `LOOKBACK_BUFFER_DIR` on
`/dev/shm/clutchcam` so the rolling buffer uses RAM-backed storage instead of
continuously writing short media segments to SSD.

## Audio Extraction

`src/services/transcription.py` includes the first audio extraction boundary and
FFmpeg command builder. It uses the same stable stream IDs as the ingest and
buffer services, and it normalizes stream audio into chunk references for the
Faster-Whisper adapter. In the integrated local Linux path, the orchestrator
owns live audio extraction when `LIVE_TRANSCRIPTION_ENABLED=true`; the
standalone `transcription-worker` service uses the same settings only when run
explicitly for JSONL diagnostics.

```text
FFMPEG_EXECUTABLE=ffmpeg
AUDIO_EXTRACT_DIR=/dev/shm/clutchcam-audio
AUDIO_EXTRACT_SAMPLE_RATE=16000
AUDIO_EXTRACT_CHANNELS=1
AUDIO_EXTRACT_CHUNK_SECONDS=5
AUDIO_EXTRACT_CODEC=pcm_s16le
AUDIO_EXTRACT_CONTAINER=wav
TRANSCRIPTION_REQUEST_OVERLAP_SECONDS=0
AUDIO_INPUT_URL_PLAYER_1=rtmp://media-server:1935/live/player_1
AUDIO_INPUT_URL_PLAYER_2=rtmp://media-server:1935/live/player_2
AUDIO_INPUT_URL_PLAYER_3=rtmp://media-server:1935/live/player_3
AUDIO_INPUT_URL_PLAYER_4=rtmp://media-server:1935/live/player_4
```

If a per-player audio input URL is not set, it falls back to
`LOOKBACK_INPUT_URL_<PLAYER>` and then `<INGEST_API_URL>/<stream_id>`. The
orchestrator and diagnostic worker should not be run as simultaneous
transcription owners for the same live inputs.
`TRANSCRIPTION_REQUEST_OVERLAP_SECONDS` is disabled by default. When set above
zero, it must be less than `AUDIO_EXTRACT_CHUNK_SECONDS` and requires
`AUDIO_EXTRACT_CONTAINER=wav`; each request after a stream's first chunk
includes that much audio tail from the previous chunk while the worker drops
transcript events that end entirely before the current chunk start.

## Transcription API Adapter

`src/services/transcription.py` also includes `FasterWhisperTranscriber`, an
HTTP adapter for Faster-Whisper-compatible services. Its default app-facing
contract posts extracted audio chunk references as JSON to
`<TRANSCRIPTION_API_URL>/transcribe`. Set
`TRANSCRIPTION_REQUEST_MODE=openai-compatible` to upload local extracted audio
chunks as multipart form data to
`<TRANSCRIPTION_API_URL>/v1/audio/transcriptions`, which matches stock
OpenAI-compatible Faster-Whisper servers. Both modes accept common text and
segment response shapes, preserve stream identity, shift chunk-relative
timestamps by the audio reference start time, and emit normalized
`TranscriptEvent` objects. Multipart mode can only upload local paths or
`file://` URIs that the worker can read.
Overlapped transcription requests require timestamped segment responses so the
worker can discard overlap-only text without duplicating downstream transcript
events; non-overlapped text-only responses keep using the full audio reference
duration.

Docker Compose also includes an optional `faster-whisper` service for local
Faster-Whisper hosting. Its documented default image is
`fedirz/faster-whisper-server:latest-cpu`, an OpenAI-compatible server whose
direct transcription API is `POST /v1/audio/transcriptions` with multipart
audio uploads. Keep `TRANSCRIPTION_API_URL` as the endpoint root: point it at a
local Compose service, a host service, or a remote endpoint, then choose the
request mode that matches that service.

Runtime settings:

```text
TRANSCRIPTION_API_URL=http://host.docker.internal:8000
# TRANSCRIPTION_API_URL=http://faster-whisper:8000
# TRANSCRIPTION_API_URL=https://stt-gpu.example.internal
TRANSCRIPTION_REQUEST_MODE=json
# TRANSCRIPTION_REQUEST_MODE=openai-compatible
# TRANSCRIPTION_ENDPOINT_PATH=/v1/audio/transcriptions
TRANSCRIPTION_MODEL=Systran/faster-whisper-small
TRANSCRIPTION_LANGUAGE=
TRANSCRIPTION_RESPONSE_FORMAT=json
TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS=30
TRANSCRIPTION_REQUEST_OVERLAP_SECONDS=0
LIVE_TRANSCRIPTION_ENABLED=false
LIVE_TRANSCRIPTION_QUEUE_SIZE=16
TRANSCRIPT_LOG_TEXT_ENABLED=false
TRANSCRIPT_LOG_TEXT_MAX_CHARACTERS=160
```

The adapter is unit-tested with mocked HTTP responses and does not require a
live Faster-Whisper container for local validation. `src/main.py` starts the
in-process live source only when `LIVE_TRANSCRIPTION_ENABLED=true`; otherwise
the terminal prompt remains the transcript source.
For transcript quality evaluation, `TRANSCRIPT_LOG_TEXT_ENABLED=true` logs
accepted runtime transcript text before prefiltering. Keep it disabled for
normal runs because player speech can be sensitive.

## Standalone Transcription Worker Diagnostics

The `transcription-worker` Compose service is an explicit diagnostic and
healthcheck target. It emits JSONL transcript and failure records from the same
FFmpeg and transcription adapter boundaries, but it is not part of the default
integrated local Linux profile set. Run it only when you want to inspect that
path separately:

```bash
TRANSCRIPTION_API_URL=http://host.docker.internal:8000 \
COMPOSE_PROFILES=media-server,transcription-worker \
docker compose up -d --build transcription-worker
```

## Optional Local Faster-Whisper Profile

The local transcription server is disabled by default and is not part of the
default local Linux runtime. Start it only when the host has enough CPU/GPU
capacity and you want a local Faster-Whisper-compatible API nearby:

```bash
COMPOSE_PROFILES=local-transcription docker compose up -d faster-whisper
```

Useful environment knobs:

```text
FASTER_WHISPER_IMAGE=fedirz/faster-whisper-server:latest-cpu
# FASTER_WHISPER_IMAGE=fedirz/faster-whisper-server:latest-cuda
FASTER_WHISPER_BIND_ADDR=127.0.0.1
FASTER_WHISPER_PORT=8000
FASTER_WHISPER_CACHE_HOST_DIR=faster-whisper-cache
FASTER_WHISPER_MODEL=Systran/faster-whisper-small
FASTER_WHISPER_DEVICE=cpu
# FASTER_WHISPER_DEVICE=cuda
FASTER_WHISPER_DEVICE_INDEX=0
FASTER_WHISPER_COMPUTE_TYPE=int8
# FASTER_WHISPER_COMPUTE_TYPE=float16
FASTER_WHISPER_CPU_THREADS=0
FASTER_WHISPER_NUM_WORKERS=1
FASTER_WHISPER_TTL_SECONDS=300
FASTER_WHISPER_PRELOAD_MODELS=[]
```

The CPU image is the conservative default. NVIDIA hosts can switch to the CUDA
image, set `FASTER_WHISPER_DEVICE=cuda`, and expose GPUs with a local Compose
override when the Docker daemon does not provide them automatically. Keep
`FASTER_WHISPER_BIND_ADDR=127.0.0.1` unless the transcription API is meant to be
reachable from other machines.

Direct OpenAI-compatible server check:

```bash
curl http://127.0.0.1:8000/v1/audio/transcriptions \
  -F "file=@/path/to/audio.wav" \
  -F "model=Systran/faster-whisper-small"
```

## Running With Docker Compose

Start the app stack, including the local media server:

```powershell
docker compose up --build app
```

On first run, Docker Compose will start SRS, start Ollama, and pull the
configured model. The model pull can take a while.

If terminal input feels awkward through `docker compose up`, run the app as an interactive one-off container:

```powershell
docker compose up -d ollama
docker compose up -d media-server
docker compose run --rm ollama-pull
docker compose run --rm app
```

At startup, the app checks that the configured Gemma/Ollama endpoint is reachable and that `GEMMA_MODEL` appears in the model list. If the model is missing, pull it before starting the app:

```powershell
ollama pull gemma3:4b
```

## Linux Local Stack Smoke Sequence

The `scripts/smoke_*.py` entrypoints are no-player smoke checks for the local
Linux stack. They are import-safe, timeout-bound, and environment-driven. Unit
tests mock subprocess and HTTP boundaries, so these scripts can be validated
without Docker, FFmpeg, SRS, OBS, GPUs, cloud credentials, or live network
endpoints.

From `ai-stream-director/`, start the local media and buffer services:

```bash
COMPOSE_PROFILES=media-server,buffer-worker \
docker compose up -d --build media-server buffer-worker
```

Smoke SRS readiness and publish one short generated RTMP source. Omit
`--no-compose` if you want the script to start the `media-server` service for
you.

```bash
SMOKE_PUBLISH_STREAMS=player_1 \
python scripts/smoke_media_server.py --no-compose
```

Expected result: JSON with the SRS summaries URL and a `publish_results` entry
for `player_1`. A failure names the failed Docker, HTTP, or FFmpeg boundary and
uses the configured timeout. Set `SMOKE_SKIP_PUBLISH=true` to check only
`/api/v1/summaries`, or set `SRS_HTTP_API_URL`/`SRS_RTMP_HOST` to target a
remote media server.

After FFmpeg has published for a few seconds, inspect the host buffer directory:

```bash
sleep 4
LOOKBACK_BUFFER_DIR=${LOOKBACK_BUFFER_HOST_DIR:-/dev/shm/clutchcam} \
SMOKE_BUFFER_STREAM_IDS=player_1 \
python scripts/smoke_buffer_worker.py
```

Expected result: JSON reporting stream IDs, latest segment metadata, and a
`clip_status` of `ready` for at least one stream. `pending` or `unavailable`
results include a reason, such as missing `segments.csv` metadata or absent
segment files.

Optionally start the local Faster-Whisper server profile and probe its
OpenAI-compatible endpoint directly:

```bash
COMPOSE_PROFILES=local-transcription docker compose up -d faster-whisper
curl http://127.0.0.1:8000/v1/audio/transcriptions \
  -F "file=@/path/to/audio.wav" \
  -F "model=Systran/faster-whisper-small"
```

Smoke a ClutchCam-compatible transcription endpoint when one is available:

```bash
TRANSCRIPTION_API_URL=http://127.0.0.1:8000 \
python scripts/smoke_transcription_api.py
```

Expected result: JSON with `<TRANSCRIPTION_API_URL>/transcribe`, the generated
fixture audio URI, request timeout, and transcript event count. Set
`SMOKE_TRANSCRIPTION_AUDIO_URI` to an endpoint-readable fixture when the API
runs on another machine or container. The smoke script validates the current
JSON `/transcribe` adapter contract. For the stock
`fedirz/faster-whisper-server` container, set
`TRANSCRIPTION_REQUEST_MODE=openai-compatible` in the worker runtime or use the
direct `/v1/audio/transcriptions` upload check shown above.

Smoke the configured AI endpoint. For Ollama, the smoke verifies that
`GEMMA_MODEL` appears in `/api/tags`:

```bash
AI_PROVIDER=ollama \
GEMMA_API_URL=http://127.0.0.1:11434 \
GEMMA_MODEL=gemma3:4b \
python scripts/smoke_ai_endpoint.py
```

Expected result: JSON with `provider`, `endpoint_url`, `probe_url`, `model`,
`timeout_seconds`, `available_models`, and `detected_model_count`. If the
configured Ollama model is missing, the failure includes the detected models and
the exact recovery command, such as `ollama pull gemma3:4b`.

For an OpenAI-compatible server, the smoke checks reachability and sends an
authorization header when `GEMMA_API_KEY` is set:

```bash
AI_PROVIDER=openai-compatible \
GEMMA_API_URL=https://gemma-gpu.example.internal/v1/chat/completions \
GEMMA_MODEL=google/gemma-3-4b-it \
python scripts/smoke_ai_endpoint.py
```

Expected result: JSON with the configured `endpoint_url`, the provider-neutral
reachability `probe_url`, the configured `model`, and `api_key_configured`.
The smoke does not require a provider-specific model-list endpoint for this
mode.

Smoke the terminal orchestrator without OBS, Ollama, or cloud credentials:

```bash
python scripts/smoke_orchestrator_dry_run.py
```

By default this starts `src/main.py` with `DRY_RUN_OBS=true`, feeds `/status`,
`/ai off`, a deterministic transcript line, `/p2`, `/quad`, and `/quit`, and
serves a tiny localhost OpenAI-compatible readiness fixture. Expected output in
the JSON `stdout` field includes `DRY_RUN_OBS enabled`,
`[DRY RUN OBS] Starting scene: Quad View`, `Manual command applied.`, and
`Exiting.` Set `SMOKE_ORCHESTRATOR_FAKE_AI=false` to use your real
`GEMMA_API_URL` instead.

When a transcription endpoint is reachable, the first integrated live check can
still avoid real OBS. Keep `transcription-worker` out of `COMPOSE_PROFILES` so
the orchestrator is the only audio extraction owner:

```bash
DRY_RUN_OBS=true \
LIVE_TRANSCRIPTION_ENABLED=true \
TRANSCRIPT_LOG_TEXT_ENABLED=true \
TRANSCRIPTION_API_URL=http://host.docker.internal:8000 \
COMPOSE_PROFILES=local-linux \
docker compose run --rm orchestrator
```

Shut the local stack down when the smoke pass is complete:

```bash
COMPOSE_PROFILES=local-linux \
docker compose down
```

## Terminal Input Format

The terminal prompt runs separately from the scheduler. Scene timers continue to tick while the app waits for transcript lines or manual commands.

Transcript lines should use this format:

```text
player_1: I am just walking around
player_2: I am mining some stone
player_3: no way, I just found something crazy
player_4: I am still loading in
```

Each accepted transcript line updates the rolling transcript history and asks Ollama for a JSON decision.

## Manual Commands

Manual commands override AI decisions:

```text
/quad
/p1
/p2
/p3
/p4
/ai on
/ai off
/status
/quit
```

## Director Rules

The scheduler enforces these rules:

- Default scene is `Quad View`.
- AI decisions below `0.75` confidence are ignored.
- Minimum time between scene switches is `8` seconds.
- Maximum focus duration is `20` seconds.
- After a player focus moment ends, the app returns to `Quad View`.
- Manual commands switch immediately.

## AI Output Format

The Ollama prompt asks the model to return JSON only:

```json
{
  "target_scene": "Player 3 Fullscreen",
  "confidence": 0.88,
  "duration_seconds": 12,
  "reason": "Player 3 expressed excitement and appears to have found something interesting."
}
```

The app validates the scene name, confidence, duration, and reason before handing the result to the scheduler.

The parser also tolerates small formatting mistakes from local models, such as markdown JSON fences, short text before or after the JSON object, and trailing commas. The final decision must still be a JSON object, and unsupported scene names are reset to `Quad View`.

## Troubleshooting

If startup prints `AI director is not ready: Ollama is not reachable`, start Ollama or check `GEMMA_API_URL`.

If startup prints that the configured model is not installed, run:

```powershell
ollama pull gemma3:4b
```

Replace `gemma3:4b` with your `GEMMA_MODEL` value if you changed it.
The AI endpoint smoke prints the same exact `ollama pull <model>` command and
the detected local model tags to make this checkpoint easier to diagnose.

If a transcript line prints `AI decision failed`, Ollama responded but did not produce a usable final decision object. Try the line again, use a lower-temperature model, or switch to a model that follows JSON instructions more reliably.

## Test Plan

Validate the rolling lookback buffer logic without FFmpeg or live inputs:

```powershell
python -m unittest tests.test_rolling_buffer -v
```

Validate the transcription HTTP adapter without network access:

```powershell
python -m unittest tests.test_transcription_event_api -v
```

For local smoke testing without OBS, set `DRY_RUN_OBS=true` in `.env` or in your shell. The app should start even when OBS is closed, `/status` should show the current dry-run scene, and manual or AI-driven scene changes should print as `[DRY RUN OBS] Scene switch: ...`.

Start with calm lines. The AI should usually keep `Quad View`.

```text
player_1: I am walking through the forest
player_2: I am crafting a pickaxe
player_3: I am checking my inventory
player_4: I am still loading in
```

Try an obvious Player 3 focus moment. The AI should choose `Player 3 Fullscreen` if confidence is high enough.

```text
player_3: no way, I just found something crazy
```

Try a rare item moment.

```text
player_2: wait, I just caught a rare fish
```

Try a low-signal message. The AI should prefer `Quad View` or return low confidence.

```text
player_1: I am going over here
```

Test cooldown behavior by sending two exciting lines back-to-back:

```text
player_1: oh wow, look at this
player_4: huge moment, I found the boss room
```

The second switch should be ignored if it happens inside the cooldown window.

Test manual override:

```text
/p4
/quad
/ai off
player_2: no way, I found diamonds
/ai on
/status
```

## Windows Local AI Dry Run

This path runs the terminal MVP directly from Windows PowerShell with host-local
Ollama and dry-run OBS. Docker, SRS, and OBS are not required for this AI loop.

Use `http://127.0.0.1:11434` when `python src/main.py` runs directly on the
Windows host. Use `http://ollama:11434` only for Docker Compose
service-to-service traffic, where `ollama` is the Compose service DNS name.

Install Ollama for Windows, start the Ollama app or service, and confirm the CLI
can reach it:

```powershell
ollama --version
ollama pull gemma3:4b
```

If the pull cannot connect, start Ollama and retry. One foreground option is to
run `ollama serve` in a separate PowerShell window.

From `ai-stream-director/`, create the Python environment and start the app:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
ollama pull gemma3:4b
$env:DRY_RUN_OBS="true"
$env:GEMMA_MODEL="gemma3:4b"
$env:GEMMA_API_URL="http://127.0.0.1:11434"
$env:OLLAMA_MODEL="gemma3:4b"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
python scripts/smoke_ai_endpoint.py
python src/main.py
```

After the prompt appears, paste a short manual transcript and command path:

```text
/status
player_1: I am walking through the forest
player_3: no way, I just found something crazy
/p2
/quad
/quit
```

Expected result: startup prints `DRY_RUN_OBS enabled` and
`[DRY RUN OBS] Starting scene: Quad View`; `/status` prints the current scene
and AI state; transcript lines are accepted and sent to host-local Ollama; a
high-confidence AI decision may print `[DRY RUN OBS] Scene switch: Player 3
Fullscreen`; manual `/p2` and `/quad` commands print deterministic dry-run
scene-switch output.

## Next Steps

The next implementation work is tracked in Tess tickets under `../tickets/` and
summarized in `../docs/ROADMAP.md`.

The most important near-term shift is wiring the implemented audio extraction
and transcription adapter into runtime `TranscriptEvent` flow while keeping the
scheduler and OBS controller mostly unchanged. Follow-up tickets wire the
implemented media ingest and rolling lookback buffer behind `src/services/`
before buffered switching uses `LookbackClipRequest` to cut to media from before
a trigger.
