# Linux And Cloud Deployment Topology Runbook

ClutchCam is local-first: live media ingest, rolling buffers, OBS control, and
operator recovery should stay close to the event network. AI and transcription
may stay host-local, move to a second Linux GPU host, or later move behind
cloud GPU HTTP endpoints without changing the app-facing contracts.

Use this runbook with [Local Linux Compose stack](local-linux-compose.md). Keep
all topology changes environment-driven; do not hard-code host names, cloud
addresses, provider secrets, or GPU assumptions into application code.

For real OBS reachability checks and the section-one acceptance checklist, use
[Real OBS connection checkpoint](real-obs-connection.md). OBS control stays on
the event network, even when AI or transcription move elsewhere.

## Stable Service Contracts

These settings are the deployment boundary:

```text
INGEST_API_URL=rtmp://media-server:1935/live
GEMMA_API_URL=http://ollama:11434
TRANSCRIPTION_API_URL=http://host.docker.internal:8000
```

`GEMMA_API_URL` may point at local Ollama, host-local vLLM, a LAN GPU server, or
a cloud OpenAI-compatible chat-completions endpoint. `TRANSCRIPTION_API_URL`
may point at a host-local adapter, the optional Compose transcription service,
a LAN GPU transcription host, or a cloud speech-to-text endpoint. Select
`TRANSCRIPTION_REQUEST_MODE=json` for ClutchCam's `/transcribe` JSON-reference
contract, or `TRANSCRIPTION_REQUEST_MODE=openai-compatible` for multipart
`/v1/audio/transcriptions` endpoints.

OBS WebSocket stays separate from those service contracts. Use a reachable
`OBS_HOST`, keep `OBS_PORT=4455` unless your OBS instance is configured
otherwise, and store `OBS_PASSWORD` outside committed files.

Keep media ingest behind `INGEST_API_URL` local to the event unless a future
site-to-site network is explicitly designed for live media. Player and capture
publishers should not depend on cloud reachability during an event.

## Topology 1: One Linux Host

Use this for rehearsal, small events, and local validation.

```text
Capture/players on host or LAN
        |
        v
Linux event host
  media-server : RTMP/SRT ingest
  buffer-worker: FFmpeg segments in /dev/shm/clutchcam
  transcription-worker: audio chunks in /dev/shm/clutchcam-audio
  faster-whisper or host STT endpoint
  ollama or host AI endpoint
  orchestrator -> OBS WebSocket
```

Recommended binds:

```text
SRS_BIND_ADDR=127.0.0.1        # host-only generated ingest
SRS_BIND_ADDR=0.0.0.0          # LAN publishers, firewall required
OLLAMA_BIND_ADDR=127.0.0.1     # keep local unless LAN inference is intended
FASTER_WHISPER_BIND_ADDR=127.0.0.1
```

Endpoint examples:

```text
AI_PROVIDER=ollama
GEMMA_API_URL=http://ollama:11434
TRANSCRIPTION_API_URL=http://host.docker.internal:8000
```

Keep `/dev/shm/clutchcam` and `/dev/shm/clutchcam-audio` RAM-backed and sized
for the event profile. The rolling buffer should contain only short-lived media
segments and generated playlists, not durable archives.

## Topology 2: Two Linux Hosts

Use this when media ingest must remain on the event host but AI or
speech-to-text needs a separate GPU box.

```text
Capture/players on LAN
        |
        v
Linux event host
  media-server
  buffer-worker in /dev/shm/clutchcam
  transcription-worker audio extraction
  orchestrator -> OBS WebSocket
        |
        | HTTP(S), firewall allowlist
        v
Linux GPU host
  Gemma endpoint: Ollama, vLLM, or compatible server
  STT endpoint: Faster-Whisper-compatible adapter
```

Keep SRS and OBS near the operator. Move only HTTP endpoint-backed services
across hosts:

- May move: Gemma inference behind `GEMMA_API_URL`.
- May move: transcription behind `TRANSCRIPTION_API_URL`.
- Usually local: `media-server`, `buffer-worker`, audio extraction,
  orchestrator, OBS/PyVMIX control.
- Local-only for now: resolved lookback media files under the event host's
  RAM-backed buffer path.

Endpoint examples:

```text
AI_PROVIDER=openai-compatible
GEMMA_API_URL=http://gpu-host.lan:8000/v1/chat/completions
GEMMA_MODEL=google/gemma-3-4b-it
TRANSCRIPTION_API_URL=http://gpu-host.lan:8001
```

Bind GPU services to a LAN interface only when the firewall limits callers to
the event host. Prefer private DNS names or static DHCP reservations over
embedding changing IP addresses in runbooks.

## Topology 3: Future Cloud GPU Or VM

Use this when local event hardware keeps ingest and switching stable while
cloud GPU capacity handles inference.

```text
Capture/players on event LAN
        |
        v
Linux event host
  media-server, buffer-worker, audio extraction
  orchestrator, OBS/PyVMIX control
        |
        | outbound HTTPS
        v
Cloud GPU/VM endpoint
  OpenAI-compatible Gemma API
  Faster-Whisper-compatible STT API
```

Cloud endpoints should be treated as replaceable HTTP services. The event host
should require only outbound HTTPS to them, plus DNS and secret configuration.
Do not move RTMP/SRT ingest, RAM-backed lookback storage, or OBS switching to
cloud VMs until the media transport, latency budget, and failure behavior are
designed explicitly.

Endpoint examples:

```text
AI_PROVIDER=openai-compatible
GEMMA_API_URL=https://gemma-gpu.example.internal/v1/chat/completions
GEMMA_API_KEY=<secret-from-env-or-secret-store>
TRANSCRIPTION_API_URL=https://stt-gpu.example.internal
```

## Firewall Ports

Open only the ports required for the selected topology.

| Service | Default | Protocol | Expose to |
| --- | ---: | --- | --- |
| SRS RTMP ingest | 1935 | TCP | LAN publishers only |
| SRS HTTP API | 1985 | TCP | Event host/admin network only |
| SRS HTTP-FLV/HLS | 8080 | TCP | Event host or trusted preview clients |
| SRS SRT ingest/playback | 10080 | UDP | LAN publishers/preview clients only |
| OBS WebSocket | 4455 | TCP | Event host only when possible |
| Local Ollama | 11434 | TCP | Event host only by default |
| Faster-Whisper service | 8000 | TCP | Event host, or allowlisted LAN/cloud |
| vLLM/OpenAI-compatible API | 8000 or 443 | TCP | Event host only |

Use `SRS_BIND_ADDR=127.0.0.1` for host-only tests and `SRS_BIND_ADDR=0.0.0.0`
only when LAN publishers need to connect. For remote AI or transcription, prefer
HTTPS on `443` across network boundaries.

## GPU And Runtime Assumptions

The default local transcription image is CPU-safe. NVIDIA acceleration requires
a CUDA-capable image, working host drivers, an NVIDIA container runtime or
equivalent Docker GPU exposure, and matching model settings:

```text
FASTER_WHISPER_IMAGE=fedirz/faster-whisper-server:latest-cuda
FASTER_WHISPER_DEVICE=cuda
FASTER_WHISPER_COMPUTE_TYPE=float16
```

Do not assume GPUs are available to Compose just because the host has a GPU.
Document any local Compose override that exposes GPU devices alongside the host
setup, but keep it out of shared defaults unless all target hosts support it.

## RAM-Backed Storage

The event host owns lookback media. Keep these paths on RAM-backed Linux storage
for low latency and automatic cleanup on reboot:

```text
LOOKBACK_BUFFER_HOST_DIR=/dev/shm/clutchcam
AUDIO_EXTRACT_HOST_DIR=/dev/shm/clutchcam-audio
```

Size `/dev/shm` for the number of streams, bitrate, lookback window, and audio
chunk retention. If a host cannot spare enough RAM, prefer reducing retention
or bitrate before moving the buffer to slow persistent storage.

## Secrets

Keep secrets in local `.env` files, host secret stores, or orchestrator-managed
deployment secrets. Never commit real values for:

- `GEMMA_API_KEY`
- `OBS_PASSWORD`
- Cloud endpoint bearer tokens
- Provider-specific STT credentials

Use placeholder values in examples. For shared event machines, rotate tokens
after rehearsals and events, especially if logs or shell history may include
environment dumps.

## Validation Without Live Infrastructure

Use documentation checks for topology edits:

```bash
rg -n "linux-cloud-deployment-topology|GEMMA_API_URL|TRANSCRIPTION_API_URL" docs ai-stream-director/.env.example
rg -n "SRS_BIND_ADDR|FASTER_WHISPER_BIND_ADDR|LOOKBACK_BUFFER_HOST_DIR|GEMMA_API_KEY" docs/runbooks ai-stream-director/.env.example
```

Do not run live Docker, GPU, or cloud commands for this docs-only topology
validation.
