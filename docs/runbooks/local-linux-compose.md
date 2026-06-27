# Local Linux Compose Runbook

Use this path on a Linux host when validating the local media-server, buffer,
transcription adapter, AI endpoint, and dry-run orchestrator boundaries. The
stack is useful for event rehearsal, but full live Linux validation across SRS,
FFmpeg, transcription, AI, and real OBS playback still needs to be completed on
event hardware. Generated RTMP validation across SRS, FFmpeg, the rolling
buffer, local Ollama, and the dry-run orchestrator has passed on
`clutchcam-media-1`; see the completed Linux generated-ingest acceptance ticket
for retained evidence.

## What This Runs

The Compose stack currently provides:

- `media-server`: local SRS RTMP/SRT ingest and HTTP inspection.
- `buffer-worker`: FFmpeg rolling lookback segments under `/dev/shm/clutchcam`.
- `orchestrator`: the terminal MVP, real or dry-run OBS switching, and an
  opt-in in-process live transcription source.
- `transcription-worker`: explicit JSONL diagnostics for FFmpeg audio chunks
  plus calls to a configured Faster-Whisper-compatible HTTP endpoint.
- `ollama` and `ollama-pull`: optional local AI profile.
- `faster-whisper`: optional local transcription server profile.

The integrated `local-linux` profile starts the media server, rolling buffer,
and orchestrator path. It does not start `transcription-worker`, because live
orchestrator transcription and the standalone worker would otherwise duplicate
audio extraction and Faster-Whisper requests for the same player feeds. Set
`LIVE_TRANSCRIPTION_ENABLED=true` when the orchestrator should own live
transcript events; run `transcription-worker` separately only for diagnostic
JSONL output.

The local Faster-Whisper server is opt-in through the `local-transcription`
profile and is not part of the default local Linux runtime. Keep
`TRANSCRIPTION_API_URL` as the app-facing contract; point it at a local Compose
service, a host service, or a remote service, then choose
`TRANSCRIPTION_REQUEST_MODE=json` for the default `/transcribe` JSON-reference
contract or `TRANSCRIPTION_REQUEST_MODE=openai-compatible` for multipart
uploads to `/v1/audio/transcriptions`. The bundled `faster-whisper` service
uses the OpenAI-compatible `fedirz/faster-whisper-server` image.

The OBS buffered media-source adapter is implemented behind the switcher
boundary. It updates a known OBS Media Source from a resolved clip URI before
cutting to the target scene. The default terminal MVP path still switches
existing scenes immediately unless a runtime caller injects that media-source
switcher.

## Host Setup

From the repo root:

```bash
cd ai-stream-director
cp .env.example .env
mkdir -p /dev/shm/clutchcam /dev/shm/clutchcam-audio
docker --version
docker compose version
ffmpeg -version
```

FFmpeg is required in two places. The generated-ingest checkpoint uses the
Linux host's `ffmpeg` command to publish bounded test streams. The shared
ClutchCam runtime image installs its own FFmpeg package for `buffer-worker`,
`orchestrator` live transcription, and `transcription-worker` diagnostics; a
host installation is not mounted into those containers.

For host-only testing, keep this in `.env`:

```text
SRS_BIND_ADDR=127.0.0.1
```

For player or capture machines on the LAN, expose SRS intentionally and open the
matching firewall ports:

```text
SRS_BIND_ADDR=0.0.0.0
SRS_RTMP_PORT=1935
SRS_HTTP_API_PORT=1985
SRS_HTTP_STREAM_PORT=8080
SRS_SRT_PORT=10080
```

Use the Linux host LAN IP in publisher URLs. Do not give player machines
`127.0.0.1`; that points them back at themselves.

## Runtime Config And Secrets

Runtime config is validated before workers start any long-running local work.
Use absolute endpoint URLs: `INGEST_API_URL`, `LOOKBACK_INPUT_URL_PLAYER_N`,
and `AUDIO_INPUT_URL_PLAYER_N` accept `rtmp`, `rtmps`, `srt`, `http`, `https`,
or `file` URLs; `GEMMA_API_URL` and `TRANSCRIPTION_API_URL` must be `http` or
`https`. Ports must be in the TCP range, stream IDs stay fixed to `player_1`
through `player_4`, durations and sample counts must be positive where they
drive workers, and runtime paths such as `LOOKBACK_BUFFER_DIR`,
`AUDIO_EXTRACT_DIR`, and `FFMPEG_EXECUTABLE` must be non-empty.

Keep dry-run ergonomics intact by setting `DRY_RUN_OBS=true` for smoke tests
that do not need OBS, Docker GPU access, or cloud services. OpenAI-compatible
Gemma endpoints may be keyless for local vLLM-style servers; set
`GEMMA_API_KEY` only when the endpoint requires bearer auth. Do not put real
secrets in committed files. Structured health/config details redact
`GEMMA_API_KEY`, `OBS_PASSWORD`, and future secret-shaped key, token, password,
or secret fields before JSON output.

## Start Local Services

Start SRS and the rolling buffer:

```bash
COMPOSE_PROFILES=local-linux \
docker compose up -d --build media-server buffer-worker
```

Start optional local Ollama:

```bash
COMPOSE_PROFILES=local-ai docker compose up -d ollama
COMPOSE_PROFILES=local-ai docker compose run --rm ollama-pull
```

Start optional local Faster-Whisper on CPU:

```bash
COMPOSE_PROFILES=local-transcription docker compose up -d faster-whisper
```

The conservative defaults use the CPU image, a local-only host bind, and a
Docker volume for the Hugging Face cache:

```text
FASTER_WHISPER_IMAGE=fedirz/faster-whisper-server:latest-cpu
FASTER_WHISPER_BIND_ADDR=127.0.0.1
FASTER_WHISPER_PORT=8000
FASTER_WHISPER_CACHE_HOST_DIR=faster-whisper-cache
FASTER_WHISPER_MODEL=Systran/faster-whisper-small
FASTER_WHISPER_DEVICE=cpu
FASTER_WHISPER_COMPUTE_TYPE=int8
```

For NVIDIA hosts, set the CUDA image and device settings, and add a local
Compose override that exposes GPUs if your Docker daemon does not do so by
default:

```text
FASTER_WHISPER_IMAGE=fedirz/faster-whisper-server:latest-cuda
FASTER_WHISPER_DEVICE=cuda
FASTER_WHISPER_COMPUTE_TYPE=float16
FASTER_WHISPER_DEVICE_INDEX=0
```

Run the orchestrator in terminal-only dry-run OBS mode:

```bash
DRY_RUN_OBS=true \
LIVE_TRANSCRIPTION_ENABLED=false \
COMPOSE_PROFILES=local-linux \
docker compose run --rm orchestrator
```

Run the orchestrator with live transcription and dry-run OBS after
`TRANSCRIPTION_API_URL` points at a reachable service:

```bash
DRY_RUN_OBS=true \
LIVE_TRANSCRIPTION_ENABLED=true \
TRANSCRIPTION_API_URL=http://host.docker.internal:8000 \
COMPOSE_PROFILES=local-linux \
docker compose run --rm orchestrator
```

Start the standalone transcription worker in the default JSON-reference mode
only when `TRANSCRIPTION_API_URL` points at a reachable service or adapter
exposing `/transcribe`. This is a diagnostic path, not part of the integrated
`local-linux` profile:

```bash
TRANSCRIPTION_API_URL=http://host.docker.internal:8000 \
COMPOSE_PROFILES=media-server,transcription-worker \
docker compose up -d --build transcription-worker
```

If you override the local service image with an adapter that exposes
ClutchCam's current `/transcribe` JSON contract, point the worker at the
Compose DNS name:

```bash
TRANSCRIPTION_API_URL=http://faster-whisper:8000 \
COMPOSE_PROFILES=media-server,transcription-worker,local-transcription \
docker compose up -d --build transcription-worker faster-whisper
```

For the stock OpenAI-compatible `faster-whisper` server, opt the worker into
multipart uploads:

```bash
TRANSCRIPTION_API_URL=http://faster-whisper:8000 \
TRANSCRIPTION_REQUEST_MODE=openai-compatible \
TRANSCRIPTION_RESPONSE_FORMAT=json \
COMPOSE_PROFILES=media-server,transcription-worker,local-transcription \
docker compose up -d --build transcription-worker faster-whisper
```

Direct upload check:

```bash
curl http://127.0.0.1:8000/v1/audio/transcriptions \
  -F "file=@/path/to/audio.wav" \
  -F "model=Systran/faster-whisper-small"
```

Run it against real OBS only after OBS WebSocket and scenes are ready:

```bash
DRY_RUN_OBS=false \
OBS_HOST=host.docker.internal \
OBS_PORT=4455 \
OBS_PASSWORD='<obs-websocket-password>' \
COMPOSE_PROFILES=local-linux \
docker compose run --rm orchestrator
```

## Player Stream Publishing

Stable stream IDs are:

```text
player_1
player_2
player_3
player_4
```

For OBS, vMix, or capture software that publishes RTMP:

```text
Server: rtmp://<linux-host-lan-ip>:1935/live
Stream key: player_1
```

Equivalent full RTMP URLs:

```text
rtmp://<linux-host-lan-ip>:1935/live/player_1
rtmp://<linux-host-lan-ip>:1935/live/player_2
rtmp://<linux-host-lan-ip>:1935/live/player_3
rtmp://<linux-host-lan-ip>:1935/live/player_4
```

For SRT publishers, use explicit publish-mode stream IDs:

```text
srt://<linux-host-lan-ip>:10080?streamid=#!::r=live/player_1,m=publish
srt://<linux-host-lan-ip>:10080?streamid=#!::r=live/player_2,m=publish
srt://<linux-host-lan-ip>:10080?streamid=#!::r=live/player_3,m=publish
srt://<linux-host-lan-ip>:10080?streamid=#!::r=live/player_4,m=publish
```

Generated RTMP source for one player:

```bash
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 \
  -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p \
  -c:a aac -f flv rtmp://127.0.0.1:1935/live/player_1
```

Generated SRT source for one player:

```bash
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 \
  -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p \
  -c:a aac -pes_payload_size 0 -f mpegts \
  "srt://127.0.0.1:10080?streamid=#!::r=live/player_1,m=publish"
```

Monitor playback from the Linux host:

```bash
ffprobe -hide_banner rtmp://127.0.0.1:1935/live/player_1
ffplay rtmp://127.0.0.1:1935/live/player_1
ffplay "srt://127.0.0.1:10080?streamid=#!::r=live/player_1,m=request"
ffplay http://127.0.0.1:8080/live/player_1.flv
```

## OBS Scene Setup

Create these scenes manually in OBS, with exact names:

- `Quad View`
- `Player 1 Fullscreen`
- `Player 2 Fullscreen`
- `Player 3 Fullscreen`
- `Player 4 Fullscreen`

The current terminal orchestrator switches between these existing scenes. Build
the scene contents yourself using the capture, network playback, or media
sources that match your event setup. For SRS preview sources, the host URLs
above are the stable starting point, especially
`http://<linux-host-lan-ip>:8080/live/player_N.flv` or
`rtmp://<linux-host-lan-ip>:1935/live/player_N`.

Do not expect the app to create scenes or create sources. For buffered playback,
create one Media Source that is present in the target scenes and name it
consistently, for example `ClutchCam Buffered Playback`. The media-source
adapter can update that existing source when given a resolved `media_uri`.
File-backed clip URIs must be reachable from the machine running OBS at the
same path; URL-backed clips must be reachable from OBS over the network.

## Smoke Tests

Run these from `ai-stream-director/`.

One-command checkpoint runner:

```bash
python scripts/checkpoint_smoke_runner.py
```

By default the runner emits structured JSON, skips live media-server, buffer,
transcription, and AI checks, and runs only the bounded orchestrator dry-run.
Each check reports `passed`, `failed`, or `skipped`, its duration, command
context, result payload, and failure reason. Opt into heavier boundaries with
per-check flags, or run the full local checkpoint when the required services are
ready:

```bash
python scripts/checkpoint_smoke_runner.py --run-media-server --run-buffer
python scripts/checkpoint_smoke_runner.py --run-all
```

Environment equivalents use `CHECKPOINT_SMOKE_RUN_<CHECK>=true` or
`CHECKPOINT_SMOKE_SKIP_<CHECK>=true`, with check names such as `MEDIA_SERVER`,
`BUFFER`, `TRANSCRIPTION`, `AI`, and `ORCHESTRATOR`.

Generated-ingest Compose checkpoint:

```bash
python scripts/compose_generated_ingest_checkpoint.py
python scripts/compose_generated_ingest_checkpoint.py --run
```

The first command is intentionally safe and emits a skipped JSON report. The
`--run` form first checks Docker Engine access, the Compose plugin, host
FFmpeg, and the writable host buffer path. It then starts `media-server` and
`buffer-worker`, waits for both services to be running and healthy, publishes
bounded generated FFmpeg RTMP streams, polls buffer metadata, and passes only
after every requested stream has a resolvable lookback clip. Add
`--reconnect-proof` when reconnect acceptance evidence is required: the
checkpoint waits for the first ready buffer, runs a second bounded publish
after `--reconnect-gap-seconds`, and passes only if the `buffer-worker`
service identity stays stable while each requested stream's latest segment
sequence advances. Use `--no-compose` to target already-running services,
`--streams player_1,player_2` to validate multiple players, and
`GENERATED_INGEST_BUFFER_READY_TIMEOUT_SECONDS` or `SMOKE_PUBLISH_SECONDS` to
give slower hosts more time. The report includes status, duration, stream IDs,
preflight results, Compose startup and service state, publish summaries, buffer
readiness, optional reconnect proof, failure reason, and operator hints.
Failed live runs also include bounded, redacted `docker compose ps` and recent
service-log evidence.

For the four-player generated-ingest acceptance path, use:

```bash
SMOKE_PUBLISH_SECONDS=12 \
python scripts/compose_generated_ingest_checkpoint.py --run \
  --streams player_1,player_2,player_3,player_4
```

For deterministic reconnect acceptance on one or more streams, use:

```bash
SMOKE_PUBLISH_SECONDS=8 \
python scripts/compose_generated_ingest_checkpoint.py --run \
  --streams player_1 \
  --reconnect-proof \
  --reconnect-gap-seconds 2
```

The reconnect proof's primary signal is data-plane advancement: the latest
segment sequence after the second publish must be greater than the sequence
captured after the first ready buffer. `buffer_ffmpeg_exited` and
`buffer_ffmpeg_started` logs are diagnostic evidence when the FFmpeg child
actually exits or restarts; they are not required when SRS keeps the RTMP
consumer process alive across bounded publishers.

Media-server readiness and generated publish:

```bash
COMPOSE_PROFILES=media-server docker compose up -d media-server
SMOKE_PUBLISH_STREAMS=player_1 python scripts/smoke_media_server.py --no-compose
```

Buffer worker clip resolution:

```bash
COMPOSE_PROFILES=media-server,buffer-worker \
docker compose up -d --build media-server buffer-worker
SMOKE_PUBLISH_STREAMS=player_1 SMOKE_PUBLISH_SECONDS=8 \
python scripts/smoke_media_server.py --no-compose
sleep 6
LOOKBACK_BUFFER_DIR=${LOOKBACK_BUFFER_HOST_DIR:-/dev/shm/clutchcam} \
SMOKE_BUFFER_STREAM_IDS=player_1 \
python scripts/smoke_buffer_worker.py
```

Local Faster-Whisper server profile, direct OpenAI-compatible upload:

```bash
COMPOSE_PROFILES=local-transcription docker compose up -d faster-whisper
curl http://127.0.0.1:8000/v1/audio/transcriptions \
  -F "file=@/path/to/audio.wav" \
  -F "model=Systran/faster-whisper-small"
```

ClutchCam transcription adapter endpoint:

```bash
TRANSCRIPTION_API_URL=http://127.0.0.1:8000 \
python scripts/smoke_transcription_api.py
```

This script posts to `<TRANSCRIPTION_API_URL>/transcribe` and does not require
Docker, GPUs, or a networked service when imported by the unit suite. Use the
OpenAI-compatible worker mode above for the stock local `faster-whisper`
service.

AI endpoint, local Ollama:

```bash
AI_PROVIDER=ollama \
GEMMA_API_URL=http://127.0.0.1:11434 \
GEMMA_MODEL=gemma3:4b \
python scripts/smoke_ai_endpoint.py
```

AI endpoint, OpenAI-compatible:

```bash
AI_PROVIDER=openai-compatible \
GEMMA_API_URL=https://gemma-gpu.example.internal/v1/chat/completions \
GEMMA_MODEL=google/gemma-3-4b-it \
GEMMA_API_KEY='<token>' \
python scripts/smoke_ai_endpoint.py
```

Orchestrator dry-run:

```bash
python scripts/smoke_orchestrator_dry_run.py
```

## Failure And Recovery

Missing stream:

- Symptom: SRS summaries are reachable, but `ffprobe` or the buffer worker
  cannot see `player_N`.
- Recover: confirm the publisher uses `/live/player_N`, check RTMP vs SRT
  publish mode, verify `SRS_BIND_ADDR=0.0.0.0` for LAN publishers, open TCP
  `1935` and UDP `10080`, then restart the publisher.
- Inspect: `docker compose logs --tail=100 media-server`.

Missing buffer segments:

- Symptom: `smoke_buffer_worker.py` reports missing `segments.csv`, no segment
  metadata, absent files, `pending`, or `unavailable`.
- Recover: verify `LOOKBACK_INPUT_URL_PLAYER_N` or `INGEST_API_URL`, check that
  the stream is live, and confirm `/dev/shm/clutchcam` is writable by the
  container. The buffer worker supervises each stream independently and
  retries FFmpeg with bounded backoff when a publisher is absent or
  disconnects; restarting the worker should not normally be required.
- Inspect: `docker compose logs --tail=100 buffer-worker`.
- Look for `buffer_ffmpeg_launch_failed`, `buffer_ffmpeg_exited`, and
  `buffer_ffmpeg_started` entries to distinguish unavailable inputs from
  successful recovery.
- A reconnect exercise should prove that the worker container identity stays
  stable and the affected stream's latest segment sequence advances after a
  second publisher connects. Use `compose_generated_ingest_checkpoint.py
  --run --reconnect-proof` for machine-verifiable evidence.
- If intentionally resetting the buffer, stop `buffer-worker` first, then clear
  only the affected stream directory under `/dev/shm/clutchcam`.

Unavailable transcription service:

- Symptom: `smoke_transcription_api.py` fails at `/transcribe`, or
  live orchestrator transcription reports chunk failures. The standalone
  `transcription-worker` diagnostic path may also emit `transcription_failure`
  JSON lines.
- Recover: start the external Faster-Whisper-compatible service, verify
  `TRANSCRIPTION_API_URL` from the host and from the container, and use
  `host.docker.internal` for a host service reached from Compose.
- For the optional local `faster-whisper` profile, inspect
  `docker compose logs --tail=100 faster-whisper`, confirm the cache volume is
  writable, and set `TRANSCRIPTION_REQUEST_MODE=openai-compatible` for worker
  uploads to `/v1/audio/transcriptions`. Use `/transcribe` only with a service
  or adapter that exposes ClutchCam's JSON-reference contract.

Unavailable AI endpoint:

- Symptom: `smoke_ai_endpoint.py` fails, the orchestrator says the AI director
  is not ready, or the configured model is missing.
- Recover: for local Ollama, start `ollama`, run the `local-ai` profile, and
  pull `GEMMA_MODEL`. For OpenAI-compatible endpoints, verify the base URL,
  auth token, and model name.
- During an event, use `/ai off` and manual OBS commands until AI is healthy.

OBS WebSocket issue:

- Symptom: real OBS mode fails to connect, fails authentication, or reports
  missing scenes.
- Recover: enable OBS WebSocket, check `OBS_HOST`, `OBS_PORT`, and
  `OBS_PASSWORD`, and verify all five scene names exactly.
- Use `DRY_RUN_OBS=true` for stack smoke tests that do not require OBS.

Buffered OBS playback unavailable:

- Symptom: the stack resolves buffer clips but OBS still switches immediately
  to the existing player scene.
- Recover: the adapter exists, but the default terminal MVP path is still
  scene-only. Use a runtime path that injects the media-source switcher, verify
  the OBS Media Source name, and confirm file or URL clip paths are reachable
  from the OBS host.

## Shutdown

```bash
COMPOSE_PROFILES=media-server,buffer-worker,transcription-worker,orchestrator,local-ai,local-transcription \
docker compose down
```
