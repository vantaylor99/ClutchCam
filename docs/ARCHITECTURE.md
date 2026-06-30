# ClutchCam Production Architecture

ClutchCam is moving from a terminal-driven OBS MVP toward a live media
orchestration system with local ingestion, a rolling lookback cache, real-time
transcription, AI-assisted trigger detection, and programmatic switching.

## Current Baseline

The existing `ai-stream-director` app is intentionally narrow. It accepts manual
terminal transcript lines, asks Gemma for a JSON scene decision through a small
provider boundary, and switches OBS scenes immediately. The default provider
keeps the current Ollama-native `/api/tags` and `/api/generate` behavior. This
is useful because it already exercises the orchestration loop, confidence
thresholds, cooldowns, manual overrides, and OBS control boundary. The same
boundary can also target OpenAI-compatible chat-completion servers such as vLLM
by selecting the provider explicitly.

The production system should keep those boundaries but replace manual transcript
input with timestamped events and immediate live switching with buffered
switching.

## Service Topology

```text
RTMP/SRT feeds
    |
    v
SRS local media server (Docker Compose)
    |
    +--> Rolling lookback buffer in /dev/shm
    |
    +--> Audio extraction
             |
             v
        Faster-Whisper API
             |
             v
       Python orchestrator
             |
             +--> local trigger rules
             +--> Gemma API endpoint
             |
             v
     OBS or PyVMIX switcher
```

The current `ai-stream-director` app is the orchestrator MVP. It already owns
the transcript-to-decision loop and OBS switching boundary. The next services
should plug into that boundary instead of rewriting it.

## Boundary Package

The importable production boundary scaffolding lives under
`ai-stream-director/src/`:

```text
contracts.py
config.py
services/
  __init__.py
  ingestion.py
  buffer.py
  transcription.py
  ai.py
  switcher.py
```

These modules define standard-library protocols, dataclasses, exceptions, and
first adapters without leaking provider details into the orchestrator. Runtime
work remains explicit. Importing them must not instantiate OBS clients, FFmpeg
subprocesses, Faster-Whisper clients, media servers, AI clients, Docker
containers, or network connections.

Production defaults remain environment-driven through `config.py`, including
`AI_PROVIDER`, `INGEST_API_URL`, `TRANSCRIPTION_API_URL`,
`TRANSCRIPTION_REQUEST_MODE`, `TRANSCRIPTION_ENDPOINT_PATH`,
`TRANSCRIPTION_MODEL`, `TRANSCRIPTION_LANGUAGE`,
`TRANSCRIPTION_RESPONSE_FORMAT`, `TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS`,
`TRANSCRIPTION_REQUEST_OVERLAP_SECONDS`, `TRANSCRIPTION_SOURCE_MODE`,
the `TRANSCRIPTION_VAD_*` local speech-pause settings,
`LIVE_TRANSCRIPTION_ENABLED`,
`LIVE_TRANSCRIPTION_QUEUE_SIZE`,
`TRANSCRIPT_LOG_TEXT_ENABLED`, `TRANSCRIPT_LOG_TEXT_MAX_CHARACTERS`,
`GEMMA_API_URL`, `GEMMA_MODEL`, optional `GEMMA_API_KEY`,
`LOOKBACK_BUFFER_DIR`, `LOOKBACK_WINDOW_SECONDS`, and
`SWITCH_LOOKBACK_SECONDS`. The lookback buffer also uses
`LOOKBACK_SEGMENT_SECONDS`, `FFMPEG_EXECUTABLE`, and optional
`LOOKBACK_INPUT_URL_PLAYER_1` through `LOOKBACK_INPUT_URL_PLAYER_4` overrides.
The transcript router keeps raw timestamped events for audit and derives
bounded same-stream utterance candidates with
`TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS`,
`TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS`,
`TRANSCRIPT_UTTERANCE_MAX_CHARACTERS`, and
`TRANSCRIPT_UTTERANCE_MAX_EVENTS` before local trigger checks.
Live transcription and the standalone diagnostic worker also use
`AUDIO_EXTRACT_DIR`, `AUDIO_EXTRACT_SAMPLE_RATE`, `AUDIO_EXTRACT_CHANNELS`,
`AUDIO_EXTRACT_CHUNK_SECONDS`, `AUDIO_EXTRACT_CODEC`,
`AUDIO_EXTRACT_CONTAINER`, and optional `AUDIO_INPUT_URL_PLAYER_1` through
`AUDIO_INPUT_URL_PLAYER_4` overrides.
For the Compose stack, `INGEST_API_URL` points workers at
`rtmp://media-server:1935/live` so stream records resolve through Docker service
DNS instead of host-published ports.
`config.py` validates locally-checkable runtime settings at load time: endpoint
URL schemes and hosts, TCP ports, fixed stream IDs, positive worker durations,
filesystem path settings, provider modes, and provider-specific endpoint/model
values. The validation stays dry-run friendly: OBS auth can be omitted when OBS
WebSocket auth is disabled or `DRY_RUN_OBS=true`, and OpenAI-compatible Gemma
endpoints can be keyless for local vLLM-style servers.

## Service Responsibilities

### Ingestion

The ingestion layer runs on local hardware and accepts RTMP or SRT streams from
the participating players or capture machines. The first concrete local ingest
implementation uses SRS through Docker Compose. The `media-server` service
mounts `ai-stream-director/infra/srs.conf`, exposes RTMP, SRT, the SRS HTTP
API, and HTTP-FLV/HLS inspection endpoints, and keeps raw player feeds on the
local network by default.

Stable stream IDs are published under the SRS `live` app:
`player_1`, `player_2`, `player_3`, and `player_4`. Worker-facing RTMP URLs use
`rtmp://media-server:1935/live/<stream_id>` inside Compose. Publisher-facing
SRT URLs use explicit stream IDs such as
`srt://<media-server-host>:10080?streamid=#!::r=live/player_1,m=publish`.
The current `services.ingestion` module describes deterministic `StreamSource`
records and URL helpers only; it does not start SRS or inspect Docker.

### Rolling Buffer

The buffer layer should keep recent media in a RAM-backed path such as
`/dev/shm/clutchcam`. The first implementation should use FFmpeg segmenting and
simple filesystem inspection before introducing more advanced media graph
management.
The current `services.buffer` module implements that first pass. It can run an
FFmpeg segment muxer per stream, rehydrate segment metadata from `segments.csv`,
prune retained `.ts` files by the configured lookback window plus segment slack,
and resolve `LookbackClipRequest` ranges into generated local playlists. Ready
clip results include both the playlist URI and the exact segment file URIs.
Fixture mode accepts synthetic `SegmentRecord` values so tests do not require
live RTMP/SRT input or an installed FFmpeg binary.

### Transcription

The transcription layer should isolate audio per stream and call a
Faster-Whisper-compatible API configured by `TRANSCRIPTION_API_URL`. It should
emit `TranscriptEvent` objects rather than leaking provider-specific response
shapes into the orchestrator.
The current `services.transcription` module defines audio input references,
transcriber/extractor protocols, fixture extraction, and an FFmpeg audio
extractor that can build and manage per-stream audio chunk workers. It also
includes a Faster-Whisper-compatible HTTP adapter that sends extracted audio
URIs to `<TRANSCRIPTION_API_URL>/transcribe` by default, or uploads local
extracted audio chunks to `<TRANSCRIPTION_API_URL>/v1/audio/transcriptions`
when `TRANSCRIPTION_REQUEST_MODE=openai-compatible`. It normalizes common text
and segment response shapes, shifts chunk-relative timestamps, uses audio chunk
duration when text-only responses omit segment timestamps, and emits
`TranscriptEvent` objects.
`TRANSCRIPTION_REQUEST_OVERLAP_SECONDS` can opt each request after a stream's
first chunk into a local WAV window containing the previous chunk tail plus the
current chunk. The worker keeps transcript timestamps on the media timeline and
drops events that end entirely before the current chunk start; overlap requires
timestamped segment responses so text-only responses do not duplicate the
previous chunk tail.

`TRANSCRIPTION_SOURCE_MODE` selects how audio becomes provider requests before
those responses normalize to `TranscriptEvent`:

- `chunked` is the default and fallback. FFmpeg segments each stream into fixed
  WAV chunks, every stable chunk is transcribed, optional WAV overlap can reduce
  missed boundary phrases, and only final transcript events reach switching.
- `vad-utterance` is optional. FFmpeg still normalizes stream audio to mono
  `pcm_s16le` WAV chunks, local voice activity detection groups speech around
  pauses before provider requests, and provider responses still normalize to the
  same transcript event contract. The existing `TranscriptRouter` still
  assembles nearby final events into bounded trigger candidates; VAD windows do
  not bypass the prefilter or AI director path.
- A future provider streaming source can plug into the same live source boundary
  if a provider emits partial and final transcript events directly. That mode is
  intentionally separate from this local pre-request VAD implementation.

The integrated local Linux path keeps one transcription owner. When
`LIVE_TRANSCRIPTION_ENABLED=true`, the orchestrator starts an in-process
`TranscriptionWorker` source and routes final events through the import-safe
`RuntimeTranscriptEventHandler`. Runtime events are routed through
`TranscriptRouter.add_event(...)`, preserving stream IDs and media end
timestamps. The router then assembles nearby final events from the same stream
into bounded utterance candidates before the local trigger prefilter and AI
director run, so provider chunk boundaries do not split phrases such as
`holy cow`. The
standalone Compose `transcription-worker` service remains an explicit JSONL
diagnostic and healthcheck path, not part of the default `local-linux` profile.
Accepted runtime transcript text can be logged for evaluation by setting
`TRANSCRIPT_LOG_TEXT_ENABLED=true`; it is off by default because transcripts can
contain private player speech. `TRANSCRIPT_LOG_TEXT_MAX_CHARACTERS` bounds each
logged transcript line.

Docker Compose can optionally start a local service named `faster-whisper`
behind the `local-transcription` profile. The documented default image is
`fedirz/faster-whisper-server:latest-cpu`, with an env-overridable CUDA image,
model, inference device, compute type, worker count, TTL, and Hugging Face cache
mount. That server's direct API is OpenAI-compatible
`POST /v1/audio/transcriptions`; the app-facing boundary remains
`TRANSCRIPTION_API_URL`, with `TRANSCRIPTION_REQUEST_MODE=openai-compatible`
selecting OpenAI-style multipart uploads.

### AI Orchestration

The AI layer should use cheap local transcript rules first, then call Gemma for
context-heavy or ambiguous moments. The implementation must not assume where
Gemma runs. `AI_PROVIDER`, `GEMMA_API_URL`, and `GEMMA_MODEL` are the primary
contract.
The current `services.ai` module accepts transcript or hybrid context and
returns optional `HypeSignal` values without assuming Ollama, Docker, local host
processes, or remote GPU inference. The MVP `AIDirector` owns prompt
construction, strict JSON decision parsing, and scene normalization, while its
provider adapter owns provider-specific readiness checks and generation
request/response shapes. `AI_PROVIDER=ollama` keeps the native Ollama `/api/tags`
and `/api/generate` flow. `AI_PROVIDER=openai-compatible` posts chat-completion
requests to the configured endpoint and parses the assistant message content as
the raw decision string before the same strict director parsing runs.

### Switching

The switcher layer should support immediate OBS scene changes during the MVP and
buffered playback for production. A positive trigger should map to a
`LookbackClipRequest`, resolve playable media, and then switch the master output.
The current `services.switcher` module keeps immediate scene changes and
buffered clip resolution behind one output-switching protocol. It can resolve a
buffered target to a ready media URI, return pending/rejected states, and pass
ready targets to a downstream scene switcher or media-source switcher. The
runtime transcript handler can build a buffered `SwitcherTarget` from an
accepted `HypeSignal` and, when an output switcher is injected, pass that target
through the buffered switching boundary. The OBS media-source path updates a
known OBS Media Source from the ready URI, reads the input settings back to
surface source/update failures before the cut, and then switches the program
scene without changing manual override, cooldown, and return-to-quad behavior.

## Core Contracts

The production services should exchange timestamped events rather than direct
process calls:

- `TranscriptEvent`: final or partial speech text for one stream, with start and
  end timestamps.
- `HypeSignal`: a transcript, vision, or hybrid signal that identifies a stream
  and trigger time.
- `LookbackClipRequest`: the stream and time range the buffer service must
  expose for switching.
- `SwitcherTarget`: the final scene/output request sent to OBS or PyVMIX,
  optionally including a resolved buffered media URI.

These contracts live in `ai-stream-director/src/contracts.py` so the MVP and
future services share one vocabulary.

## Lookback Rule

When a trigger occurs at time `T`, the output switcher should request media that
starts before the trigger:

```text
clip_start = T - SWITCH_LOOKBACK_SECONDS
clip_end   = T + post_roll
```

The rolling buffer should retain at least `LOOKBACK_WINDOW_SECONDS` of playable
segments. Defaults are a 30-second retention window and a 15-second pre-roll.

## Latency And Soak Operations

Live orchestration latency is tracked as a budgeted path across buffer
availability, transcript event routing, local prefiltering, model decision,
clip resolution, switch action, and end-to-end event handling. The offline
harness at `ai-stream-director/scripts/latency_soak_harness.py` runs this path
through the production contracts with deterministic fake model, buffer, and
switcher adapters. It does not start Docker, OBS, FFmpeg, GPU inference, or
network services by default.

Run a bounded local report from `ai-stream-director/`:

```text
python scripts/latency_soak_harness.py --events 48
```

The script emits structured JSON with event counts, accepted/rejected and
dropped/late events, per-stage timing distributions, stage budget pass/fail
results, and basic process/memory details. A nonzero exit means at least one
observed stage exceeded its configured budget. Individual budgets can be
overridden for experiments with `--budget stage=milliseconds`; live
infrastructure comparisons should remain opt-in and keep the same JSON shape so
offline, LAN, and cloud endpoint runs are comparable.

When comparing `chunked` and `vad-utterance`, operators should use the same
fixture or rehearsal stream and record missed trigger phrases, duplicate
triggers, speech-end-to-accepted-transcript latency, host CPU/GPU use,
transcription backend request count and duration, and backend cost if the
provider is remote or metered. Transcript text logging remains opt-in through
`TRANSCRIPT_LOG_TEXT_ENABLED` because player speech can be sensitive.

## Infrastructure Boundaries

The app logic must not know where inference runs. Local Ollama, local vLLM, and
cloud GPU inference should all be selected by environment variables:

- `AI_PROVIDER`
- `GEMMA_API_URL`
- `GEMMA_MODEL`
- `GEMMA_API_KEY`
- `TRANSCRIPTION_API_URL`
- `TRANSCRIPTION_REQUEST_MODE`
- `TRANSCRIPTION_SOURCE_MODE`
- `TRANSCRIPTION_ENDPOINT_PATH`
- `TRANSCRIPTION_MODEL`
- `TRANSCRIPTION_LANGUAGE`
- `TRANSCRIPTION_RESPONSE_FORMAT`
- `TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS`
- `TRANSCRIPTION_REQUEST_OVERLAP_SECONDS`
- `TRANSCRIPTION_VAD_FRAME_MS`
- `TRANSCRIPTION_VAD_ENERGY_THRESHOLD`
- `TRANSCRIPTION_VAD_MIN_SPEECH_SECONDS`
- `TRANSCRIPTION_VAD_MIN_SILENCE_SECONDS`
- `TRANSCRIPTION_VAD_LEADING_PADDING_SECONDS`
- `TRANSCRIPTION_VAD_TRAILING_PADDING_SECONDS`
- `TRANSCRIPTION_VAD_MAX_UTTERANCE_SECONDS`
- `LIVE_TRANSCRIPTION_ENABLED`
- `LIVE_TRANSCRIPTION_QUEUE_SIZE`
- `INGEST_API_URL`
- `FFMPEG_EXECUTABLE`
- `AUDIO_EXTRACT_DIR`
- `AUDIO_INPUT_URL_PLAYER_1` through `AUDIO_INPUT_URL_PLAYER_4`

`OLLAMA_BASE_URL` and `OLLAMA_MODEL` remain accepted compatibility aliases for
the current MVP.

Deployment topology is local-first. The media server, rolling lookback buffer,
audio extraction workers, orchestrator, and OBS/PyVMIX control should stay on
the event host by default because they depend on LAN ingest, RAM-backed media
paths, and low-latency operator recovery. AI and transcription are the movable
boundaries: they may run host-local, on a second Linux GPU host, or on future
cloud GPU/VM endpoints as long as `GEMMA_API_URL` and `TRANSCRIPTION_API_URL`
keep the same HTTP contracts. See
`docs/runbooks/linux-cloud-deployment-topology.md` for bind-address, firewall,
RAM-backed storage, GPU runtime, and secrets guidance.

Structured diagnostics must not leak credentials. Health reports and
config-shaped details redact `GEMMA_API_KEY`, `OBS_PASSWORD`, and future fields
with secret-shaped names such as key, token, password, secret, `apiKey`,
`accessToken`, or `refreshToken`. Runtime logs and smoke summaries should
report whether auth is configured rather than printing secret values.

Provider examples:

```text
# Local Ollama, default native provider.
AI_PROVIDER=ollama
GEMMA_API_URL=http://ollama:11434
GEMMA_MODEL=gemma3:4b

# Local vLLM or another OpenAI-compatible server.
AI_PROVIDER=openai-compatible
GEMMA_API_URL=http://vllm:8000
GEMMA_MODEL=google/gemma-3-4b-it

# Remote OpenAI-compatible endpoint with an explicit chat-completions path.
AI_PROVIDER=openai-compatible
GEMMA_API_URL=https://inference.example.com/v1/chat/completions
GEMMA_MODEL=gemma-3-4b-it
GEMMA_API_KEY=<token>
```

Transcription endpoint examples:

```text
# Host-local Faster-Whisper-compatible adapter from Compose.
TRANSCRIPTION_API_URL=http://host.docker.internal:8000
TRANSCRIPTION_REQUEST_MODE=json
TRANSCRIPTION_REQUEST_OVERLAP_SECONDS=0

# Optional Compose-network OpenAI-compatible transcription service.
TRANSCRIPTION_API_URL=http://faster-whisper:8000
TRANSCRIPTION_REQUEST_MODE=openai-compatible

# Remote/cloud speech-to-text endpoint.
TRANSCRIPTION_API_URL=https://stt-gpu.example.internal
```

## Near-Term Sequence

1. Wire the implemented local media ingest and rolling FFmpeg lookback buffer
   into runtime workers.
2. Connect the audio extraction and Faster-Whisper worker process to the
   orchestrator's normalized runtime transcript event handler.
3. Wire the OBS media-source adapter into the production runtime path and
   validate resolved buffered clip playback against live OBS.
4. Add a PyVMIX media-source adapter if vMix becomes part of the target
   switching stack.

See `docs/ROADMAP.md` for the staged implementation plan and `tickets/` for
the executable Tess backlog.
