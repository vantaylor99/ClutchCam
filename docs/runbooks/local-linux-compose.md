# Local Linux Compose Runbook

Use this path on a Linux host when validating the local media-server, buffer,
transcription adapter, AI endpoint, and dry-run orchestrator boundaries. The
stack is useful for event rehearsal, but full live Linux validation across SRS,
FFmpeg, transcription, AI, and OBS is still future work.

## What This Runs

The Compose stack currently provides:

- `media-server`: local SRS RTMP/SRT ingest and HTTP inspection.
- `buffer-worker`: FFmpeg rolling lookback segments under `/dev/shm/clutchcam`.
- `transcription-worker`: FFmpeg audio chunks plus calls to a configured
  Faster-Whisper-compatible HTTP endpoint.
- `orchestrator`: the terminal MVP, with real or dry-run OBS switching.
- `ollama` and `ollama-pull`: optional local AI profile.

There is not yet a bundled Faster-Whisper Compose profile. Point
`TRANSCRIPTION_API_URL` at an existing host, container, or remote service.

Real OBS buffered media-source playback is not implemented yet. The switcher can
resolve buffered clip URIs behind service boundaries, but the OBS adapter still
switches existing scenes immediately.

## Host Setup

From the repo root:

```bash
cd ai-stream-director
cp .env.example .env
mkdir -p /dev/shm/clutchcam /dev/shm/clutchcam-audio
docker --version
docker compose version
```

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

## Start Local Services

Start SRS and the rolling buffer:

```bash
COMPOSE_PROFILES=media-server,buffer-worker \
docker compose up -d --build media-server buffer-worker
```

Start optional local Ollama:

```bash
COMPOSE_PROFILES=local-ai docker compose up -d ollama
COMPOSE_PROFILES=local-ai docker compose run --rm ollama-pull
```

Start the transcription worker only when `TRANSCRIPTION_API_URL` points at a
reachable Faster-Whisper-compatible API:

```bash
TRANSCRIPTION_API_URL=http://host.docker.internal:8000 \
COMPOSE_PROFILES=media-server,transcription-worker \
docker compose up -d --build transcription-worker
```

Run the orchestrator in dry-run OBS mode:

```bash
DRY_RUN_OBS=true \
COMPOSE_PROFILES=orchestrator \
docker compose run --rm orchestrator
```

Run it against real OBS only after OBS WebSocket and scenes are ready:

```bash
DRY_RUN_OBS=false \
OBS_HOST=host.docker.internal \
OBS_PORT=4455 \
OBS_PASSWORD='<obs-websocket-password>' \
COMPOSE_PROFILES=orchestrator \
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

The current orchestrator only switches between these existing scenes. Build the
scene contents yourself using the capture, network playback, or media sources
that match your event setup. For SRS preview sources, the host URLs above are
the stable starting point, especially
`http://<linux-host-lan-ip>:8080/live/player_N.flv` or
`rtmp://<linux-host-lan-ip>:1935/live/player_N`.

Do not expect the app to create scenes, create sources, or update a media source
to a buffered clip. The OBS buffered media-source adapter is still future work.

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

Transcription API endpoint:

```bash
TRANSCRIPTION_API_URL=http://127.0.0.1:8000 \
python scripts/smoke_transcription_api.py
```

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
- Recover: start the buffer worker before publishing, verify
  `LOOKBACK_INPUT_URL_PLAYER_N` or `INGEST_API_URL`, check that the stream is
  live, and confirm `/dev/shm/clutchcam` is writable by the container.
- Inspect: `docker compose logs --tail=100 buffer-worker`.
- If intentionally resetting the buffer, stop `buffer-worker` first, then clear
  only the affected stream directory under `/dev/shm/clutchcam`.

Unavailable transcription service:

- Symptom: `smoke_transcription_api.py` fails at `/transcribe`, or
  `transcription-worker` emits `transcription_failure` JSON lines.
- Recover: start the external Faster-Whisper-compatible service, verify
  `TRANSCRIPTION_API_URL` from the host and from the container, and use
  `host.docker.internal` for a host service reached from Compose.
- Remember: the local Faster-Whisper Compose profile is not implemented yet.

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
- Recover: this is expected for the current MVP. A future OBS media-source
  adapter must preload or update the source with the resolved clip URI before
  cutting program output.

## Shutdown

```bash
COMPOSE_PROFILES=media-server,buffer-worker,transcription-worker,orchestrator,local-ai \
docker compose down
```
