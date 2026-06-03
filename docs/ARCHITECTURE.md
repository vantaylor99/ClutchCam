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

## Service Responsibilities

### Ingestion

The ingestion layer should run on local hardware and accept RTMP or SRT streams
from the participating players or capture machines. It should provide stable
stream IDs such as `player_1`, `player_2`, `player_3`, and `player_4`.

### Rolling Buffer

The buffer layer should keep recent media in a RAM-backed path such as
`/dev/shm/clutchcam`. The first implementation should use FFmpeg segmenting and
simple filesystem inspection before introducing more advanced media graph
management.

### Transcription

The transcription layer should isolate audio per stream and call a
Faster-Whisper-compatible API configured by `TRANSCRIPTION_API_URL`. It should
emit `TranscriptEvent` objects rather than leaking provider-specific response
shapes into the orchestrator.

### AI Orchestration

The AI layer should use cheap local transcript rules first, then call Gemma for
context-heavy or ambiguous moments. The implementation must not assume where
Gemma runs. `GEMMA_API_URL` and `GEMMA_MODEL` are the primary contract.

### Switching

The switcher layer should support immediate OBS scene changes during the MVP and
buffered playback for production. A positive trigger should map to a
`LookbackClipRequest`, resolve playable media, and then switch the master output.

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

1. Build the rolling FFmpeg lookback buffer around `/dev/shm`.
2. Add a transcription adapter that emits `TranscriptEvent` objects.
3. Generalize the AI director for OpenAI-compatible Gemma endpoints.
4. Add buffered switch playback so OBS/PyVMIX cuts to `trigger_time - pre_roll`.

See `docs/ROADMAP.md` for the staged implementation plan and `tickets/` for
the executable Tess backlog.
