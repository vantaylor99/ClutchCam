# ClutchCam Production Architecture

ClutchCam is moving from a terminal-driven OBS MVP toward a live media
orchestration system with local ingestion, a rolling lookback cache, real-time
transcription, AI-assisted trigger detection, and programmatic switching.

## Current Baseline

The existing `ai-stream-director` app is intentionally narrow. It accepts manual
terminal transcript lines, asks a local Ollama/Gemma-compatible model for a JSON
scene decision, and switches OBS scenes immediately. This is useful because it
already exercises the orchestration loop, confidence thresholds, cooldowns,
manual overrides, and OBS control boundary.

The production system should keep those boundaries but replace manual transcript
input with timestamped events and immediate live switching with buffered
switching.

## Service Topology

```text
RTMP/SRT feeds
    |
    v
Local media server
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

These modules are not running services yet. They define standard-library
protocols, dataclasses, and exceptions that future adapters can implement
without leaking provider details into the orchestrator. Importing them must not
instantiate OBS clients, FFmpeg subprocesses, Faster-Whisper clients, media
servers, AI clients, Docker containers, or network connections.

Production defaults remain environment-driven through `config.py`, including
`INGEST_API_URL`, `TRANSCRIPTION_API_URL`, `GEMMA_API_URL`, `GEMMA_MODEL`,
`LOOKBACK_BUFFER_DIR`, `LOOKBACK_WINDOW_SECONDS`, and
`SWITCH_LOOKBACK_SECONDS`.

## Service Responsibilities

### Ingestion

The ingestion layer should run on local hardware and accept RTMP or SRT streams
from the participating players or capture machines. It should provide stable
stream IDs such as `player_1`, `player_2`, `player_3`, and `player_4`.
The current `services.ingestion` module describes those `StreamSource` records
and source-provider interface only; it does not start a media server.

### Rolling Buffer

The buffer layer should keep recent media in a RAM-backed path such as
`/dev/shm/clutchcam`. The first implementation should use FFmpeg segmenting and
simple filesystem inspection before introducing more advanced media graph
management.
The current `services.buffer` module accepts `LookbackClipRequest` and returns a
ready, pending, or unavailable clip-resolution result without launching FFmpeg.

### Transcription

The transcription layer should isolate audio per stream and call a
Faster-Whisper-compatible API configured by `TRANSCRIPTION_API_URL`. It should
emit `TranscriptEvent` objects rather than leaking provider-specific response
shapes into the orchestrator.
The current `services.transcription` module defines audio input references and a
transcriber protocol only.

### AI Orchestration

The AI layer should use cheap local transcript rules first, then call Gemma for
context-heavy or ambiguous moments. The implementation must not assume where
Gemma runs. `GEMMA_API_URL` and `GEMMA_MODEL` are the primary contract.
The current `services.ai` module accepts transcript or hybrid context and
returns optional `HypeSignal` values without assuming Ollama, Docker, local host
processes, or remote GPU inference.

### Switching

The switcher layer should support immediate OBS scene changes during the MVP and
buffered playback for production. A positive trigger should map to a
`LookbackClipRequest`, resolve playable media, and then switch the master output.
The current `services.switcher` module keeps immediate scene changes and future
buffered playback behind one output-switching protocol.

## Core Contracts

The production services should exchange timestamped events rather than direct
process calls:

- `TranscriptEvent`: final or partial speech text for one stream, with start and
  end timestamps.
- `HypeSignal`: a transcript, vision, or hybrid signal that identifies a stream
  and trigger time.
- `LookbackClipRequest`: the stream and time range the buffer service must
  expose for switching.
- `SwitcherTarget`: the final scene/output request sent to OBS or PyVMIX.

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

## Infrastructure Boundaries

The app logic must not know where inference runs. Local Ollama, local vLLM, and
cloud GPU inference should all be selected by environment variables:

- `GEMMA_API_URL`
- `GEMMA_MODEL`
- `TRANSCRIPTION_API_URL`
- `INGEST_API_URL`

`OLLAMA_BASE_URL` and `OLLAMA_MODEL` remain accepted compatibility aliases for
the current MVP.

## Near-Term Sequence

1. Implement the rolling FFmpeg lookback buffer behind `services.buffer`.
2. Add local media-server ingest behind `services.ingestion`.
3. Add a transcription adapter that emits `TranscriptEvent` objects.
4. Generalize the AI director for OpenAI-compatible Gemma endpoints.
5. Add buffered switch playback so OBS/PyVMIX cuts to `trigger_time - pre_roll`.

See `docs/ROADMAP.md` for the staged implementation plan and `tickets/` for
the executable Tess backlog.
