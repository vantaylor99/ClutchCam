# ClutchCam

ClutchCam is a live media orchestration project. The current codebase contains
a local AI Stream Director MVP, and the roadmap is to grow it into a
production-grade system for ingesting multiple live feeds, caching a rolling
lookback window, transcribing audio in real time, detecting hype moments, and
switching the master output to buffered media from before the trigger.

## Current State

The working application lives in `ai-stream-director/`.

It currently:

- Connects to manually created OBS scenes over OBS WebSocket.
- Accepts terminal transcript lines for four players.
- Sends recent transcript context to a local Ollama/Gemma-compatible model.
- Applies confidence, cooldown, and focus-duration rules.
- Switches OBS scenes immediately, with a dry-run mode for local smoke tests.
- Defines lightweight production service boundaries under
  `ai-stream-director/src/services/` for ingestion, buffering, transcription,
  AI classification, and switching adapters.
- Includes first-pass local RTMP/SRT ingest and rolling lookback-buffer
  implementations behind those service boundaries.
- Includes operator runbooks for the terminal dry-run MVP and local Linux
  Compose smoke paths.

It does not yet:

- Wire RTMP/SRT video feeds into the runtime director loop.
- Run the rolling video buffer as part of the app startup path.
- Run real-time speech-to-text.
- Cut to buffered media from before a trigger.
- Run visual or multimodal hype detection.
- Provide a production deployment stack.

See `docs/STATUS.md` for the detailed repo status, and
`docs/runbooks/README.md` for operator setup and recovery runbooks.

## Target System

The intended production system is local-first:

1. RTMP/SRT inputs arrive at a local media server.
2. FFmpeg or GStreamer writes each stream to a rolling RAM-backed lookback
   buffer.
3. Audio is transcribed by Faster-Whisper through an API boundary.
4. Local Python rules and Gemma classify transcript and visual hype signals.
5. OBS, PyVMIX, or a future compositor switches the master output to buffered
   media starting roughly 10-15 seconds before the trigger.

The current `services/` modules are boundaries, not long-running daemons. First
ingest and rolling-buffer implementations exist behind those interfaces;
follow-up work wires them into the runtime director loop.

See `docs/ARCHITECTURE.md` for service boundaries and shared contracts.

## Work Management

This repo uses Tess for ticket management. Tickets live in `tickets/`, and agent
workflow rules live in `tess/agent-rules/tickets.md`.

Useful commands:

```powershell
node tess/scripts/run.mjs --dry-run
node tess/scripts/run.mjs --stages plan:20
node tess/scripts/run.mjs --stages fix,plan,implement,review
```

See `docs/ROADMAP.md` for the current implementation sequence.
