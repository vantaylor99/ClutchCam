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

Status: complete for the terminal MVP baseline. Dry-run review has passed;
live OBS scene-switching remains an operator validation step when OBS is
available.

## Phase 1 - Local Media Ingestion And Lookback

Purpose: accept multiple live feeds locally and keep a playable 30-second window
without writing continuously to SSD.

Deliverables:

- Service layout for ingestion, buffer, transcription, orchestration, and
  switcher boundaries. Boundary scaffolding exists under
  `ai-stream-director/src/services/`; behavior lands in follow-up tickets.
- Local RTMP/SRT media server configuration. First implementation exists as an
  SRS `media-server` Docker Compose service using
  `ai-stream-director/infra/srs.conf` and has completed review.
- FFmpeg-based rolling segment writer using `/dev/shm`. First implementation
  exists behind `services.buffer` and has completed review.
- Clip resolver that turns `LookbackClipRequest` into concrete media ranges.
  First implementation exists behind `services.buffer` and has completed
  review.
- Fixture mode for repeatable tests without live inputs. First implementation
  exists behind `services.buffer` and has completed review.

Success criteria:

- Four streams can be represented by stable stream IDs.
- RTMP/SRT publishers can target SRS `live/player_1` through `live/player_4`,
  and Compose workers can consume `rtmp://media-server:1935/live/<stream_id>`.
- Each stream retains at least `LOOKBACK_WINDOW_SECONDS` of media.
- A trigger at time `T` can resolve media beginning at
  `T - SWITCH_LOOKBACK_SECONDS`.

## Phase 2 - Real-Time Transcription

Purpose: replace terminal input with timestamped transcript events while keeping
the existing decision/scheduler boundary.

Deliverables:

- Audio extraction per stream. First FFmpeg command/scaffolding implementation
  exists behind `services.transcription`; runtime wiring is still pending.
- Faster-Whisper API adapter configured by `TRANSCRIPTION_API_URL`. First HTTP
  adapter implementation exists behind `services.transcription`, including the
  default JSON-reference mode and opt-in OpenAI-compatible multipart uploads;
  runtime wiring is still pending.
- `TranscriptEvent` ingestion path. `TranscriptRouter.add_event(...)` exists so
  runtime code can feed normalized events without changing the terminal MVP
  input path.
- Partial/final transcript handling in normalized transcript events.
- Error handling for unavailable, slow, or malformed transcription services.

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

- Buffer clip resolution and a buffer-backed switch target boundary.
- OBS media-source playback path that consumes resolved buffered media. The
  adapter is implemented; runtime configuration/injection and live OBS
  validation remain pending.
- Switcher interface that can later support PyVMIX.
- Manual operator override preserved.
- Cooldown, focus duration, and return-to-quad behavior preserved.

Success criteria:

- A trigger on `player_3` at `T` can switch output to media beginning roughly
  10-15 seconds before `T`.

## Phase 5 - Optional Visual And Multimodal Signals

Purpose: optionally add visual confirmation and richer hype classification after
the transcript path, lookback switching, and OBS buffered playback are stable.
This is not part of the next local testing checkpoint.

Deliverables:

- Keyframe extraction from the rolling buffer.
- Multimodal prompt adapter.
- Fusion logic for transcript and vision signals.
- False-positive tuning fixtures.

Success criteria:

- Visual analysis can confirm or reject ambiguous transcript hype without
  destabilizing the live switching path.

## Next Checkpoint - Local Generated Stream Validation

Purpose: before adding more product behavior, prove the local stack can be
started and diagnosed with generated media and bounded smoke commands.

Success criteria:

- The Python unit suite remains green.
- A single checkpoint runner can execute or skip each smoke boundary and produce
  a structured report.
- An opt-in Docker Compose checkpoint can publish a generated RTMP stream,
  produce buffer segments in `/dev/shm`, and resolve a lookback clip.
- AI and transcription endpoints fail with clear operator guidance when they are
  not configured.

Current status: the checkpoint runner, runtime healthcheck entrypoints, AI
readiness diagnostics, and opt-in generated-ingest Compose checkpoint are
implemented. The remaining checkpoint gap is running the generated-ingest
validation on a Linux host with Docker and FFmpeg.

## Phase 6 - Production Operations

Purpose: make the local-first stack observable, restartable, and deployable.

Deliverables:

- Docker Compose profile for local Linux hardware.
- Health checks for media server, buffer, transcription, AI, and orchestrator.
- Structured logs and event trace IDs.
- Sample media integration tests.
- Operator runbooks for OBS scene setup and failure recovery.

Success criteria:

- The stack can be started, smoke-tested, stopped, and restarted predictably on a
  local Linux host.

## Tess Ticket Map

Active review tickets: none.

Active implement tickets: none.

Active plan tickets: none.

Active fix tickets: none.

Completed review tickets:

- `tickets/complete/10-gemma-orchestration-adapter.md`
- `tickets/complete/11-openai-compatible-gemma-client.md`
- `tickets/complete/12-buffer-clip-resolver.md`
- `tickets/complete/13-buffered-switcher-playback.md`
- `tickets/complete/14-sample-media-integration-harness.md`
- `tickets/complete/16-local-linux-compose-stack.md`
- `tickets/complete/18-operator-runbooks.md`
- `tickets/complete/1-nonblocking-terminal-loop.md`
- `tickets/complete/2-local-smoke-test-mode.md`
- `tickets/complete/3-ollama-readiness-and-json-hardening.md`
- `tickets/complete/4-obs-connection-and-scene-validation.md`
- `tickets/complete/5-mvp-end-to-end-review.md`
- `tickets/complete/5-production-service-boundaries.md`
- `tickets/complete/6-rolling-lookback-buffer.md`
- `tickets/complete/7-local-media-server-ingest.md`
- `tickets/complete/7-transcription-audio-extraction.md`
- `tickets/complete/8-transcription-event-api.md`
- `tickets/complete/19-ai-disabled-skips-model-call.md`
- `tickets/complete/19-local-ai-dev-quickstart.md`
- `tickets/complete/20-terminal-prompt-log-interleaving.md`
- `tickets/complete/20-local-srs-dev-quickstart.md`
- `tickets/complete/21-dry-run-obs-without-obs-dependency.md`
- `tickets/complete/21-transcript-trigger-prefilter.md`
- `tickets/complete/22-transcription-runtime-pump.md`
- `tickets/complete/22-python-bytecode-artifacts-dirty-worktree.md`
- `tickets/complete/23-structured-event-logging.md`
- `tickets/complete/24-buffer-worker-runtime-entrypoint.md`
- `tickets/complete/25-transcription-worker-runtime-entrypoint.md`
- `tickets/complete/26-local-linux-compose-profiles.md`
- `tickets/complete/27-local-stack-smoke-entrypoints.md`
- `tickets/complete/28-health-check-primitives.md`
- `tickets/complete/29-obs-buffered-media-source-adapter.md`
- `tickets/complete/30-runtime-event-pipeline-wiring.md`
- `tickets/complete/31-faster-whisper-compose-profile.md`
- `tickets/complete/32-runtime-healthcheck-entrypoints.md`
- `tickets/complete/33-local-checkpoint-smoke-runner.md`
- `tickets/complete/34-compose-generated-ingest-checkpoint.md`
- `tickets/complete/35-local-ai-model-readiness-checkpoint.md`
- `tickets/complete/36-linux-cloud-deployment-topology-runbook.md`
- `tickets/complete/37-latency-budget-and-soak-harness.md`
- `tickets/complete/38-runtime-config-and-secrets-hardening.md`
- `tickets/complete/39-openai-compatible-transcription-adapter.md`

Backlog tickets:

- `tickets/backlog/90-optional-vision-keyframe-analysis.md`
