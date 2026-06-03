# Implementation Roadmap

This roadmap translates the production architecture into Tess-sized work. The
goal is to preserve the working OBS MVP while adding one production boundary at
a time.

## Phase 0 - Stabilize The MVP

Purpose: make sure the current terminal/Ollama/OBS loop remains a reliable
baseline before adding media services.

Deliverables:

- End-to-end dry-run review of current manual transcript workflow.
- Documentation aligned with the current repo state.
- Shared event contracts for production services.
- Tests around contract behavior and configuration aliases.

Status: mostly complete. A final MVP review ticket remains available.

## Phase 1 - Local Media Ingestion And Lookback

Purpose: accept multiple live feeds locally and keep a playable 30-second window
without writing continuously to SSD.

Deliverables:

- Service layout for ingestion, buffer, transcription, orchestration, and
  switcher boundaries.
- Local RTMP/SRT media server configuration.
- FFmpeg-based rolling segment writer using `/dev/shm`.
- Clip resolver that turns `LookbackClipRequest` into concrete media ranges.
- Fixture mode for repeatable tests without live inputs.

Success criteria:

- Four streams can be represented by stable stream IDs.
- Each stream retains at least `LOOKBACK_WINDOW_SECONDS` of media.
- A trigger at time `T` can resolve media beginning at
  `T - SWITCH_LOOKBACK_SECONDS`.

## Phase 2 - Real-Time Transcription

Purpose: replace terminal input with timestamped transcript events while keeping
the existing decision/scheduler boundary.

Deliverables:

- Audio extraction per stream.
- Faster-Whisper API adapter configured by `TRANSCRIPTION_API_URL`.
- `TranscriptEvent` ingestion path.
- Partial/final transcript handling.
- Error handling for unavailable or slow transcription services.

Success criteria:

- Transcripts preserve stream identity and timestamps.
- The current AI director can consume real transcript context without knowing
  whether it came from terminal input or Faster-Whisper.

## Phase 3 - AI Orchestration

Purpose: generalize from Ollama-only MVP calls to a provider boundary that can
use local or cloud Gemma endpoints.

Deliverables:

- Provider adapter for Ollama native API.
- Provider adapter for OpenAI-compatible Gemma/vLLM API.
- Local trigger pre-filter before expensive model calls.
- `HypeSignal` output from transcript decisions.
- Model prompt and JSON schema tests.

Success criteria:

- Changing `GEMMA_API_URL` and `GEMMA_MODEL` can move inference between local and
  remote providers without changing scheduler or buffer code.

## Phase 4 - Buffered Switching

Purpose: switch the master output to the buildup before the trigger instead of
only switching live.

Deliverables:

- Buffer clip resolution and playback path for OBS.
- Switcher interface that can later support PyVMIX.
- Manual operator override preserved.
- Cooldown, focus duration, and return-to-quad behavior preserved.

Success criteria:

- A trigger on `player_3` at `T` can switch output to media beginning roughly
  10-15 seconds before `T`.

## Phase 5 - Visual And Multimodal Signals

Purpose: add visual confirmation and richer hype classification after the
transcript path is stable.

Deliverables:

- Keyframe extraction from the rolling buffer.
- Multimodal prompt adapter.
- Fusion logic for transcript and vision signals.
- False-positive tuning fixtures.

Success criteria:

- Visual analysis can confirm or reject ambiguous transcript hype without
  destabilizing the live switching path.

## Phase 6 - Production Operations

Purpose: make the local-first stack observable, restartable, and deployable.

Deliverables:

- Docker Compose profile for local Linux hardware.
- Health checks for media server, buffer, transcription, AI, and switcher.
- Structured logs and event trace IDs.
- Sample media integration tests.
- Operator runbooks for OBS scene setup and failure recovery.

Success criteria:

- The stack can be started, smoke-tested, stopped, and restarted predictably on a
  local Linux host.

## Tess Ticket Map

Active plan tickets:

- `tickets/plan/5-production-service-boundaries.md`
- `tickets/plan/6-rolling-lookback-buffer.md`
- `tickets/plan/7-local-media-server-ingest.md`

Backlog tickets:

- `tickets/backlog/5-mvp-end-to-end-review.md`
- `tickets/backlog/7-transcription-audio-extraction.md`
- `tickets/backlog/8-transcription-event-api.md`
- `tickets/backlog/9-transcript-trigger-prefilter.md`
- `tickets/backlog/10-gemma-orchestration-adapter.md`
- `tickets/backlog/11-openai-compatible-gemma-client.md`
- `tickets/backlog/12-buffer-clip-resolver.md`
- `tickets/backlog/13-buffered-switcher-playback.md`
- `tickets/backlog/14-sample-media-integration-harness.md`
- `tickets/backlog/15-observability-healthchecks.md`
- `tickets/backlog/16-local-linux-compose-stack.md`
- `tickets/backlog/17-vision-keyframe-analysis.md`
- `tickets/backlog/18-operator-runbooks.md`
