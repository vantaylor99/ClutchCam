# AI Stream Director MVP

This is a local MVP for an AI-powered OBS stream director.

It does four things:

1. Connects to manually created OBS scenes through OBS WebSocket.
2. Accepts fake transcript lines for 4 players in the terminal.
3. Sends recent transcript context to a local Ollama model.
4. Switches OBS scenes when the AI finds a clear focus moment.

It does not do real transcription, video capture, stream delay, video buffering, or OBS scene creation yet.

## Production Direction

The MVP is being shaped into the ClutchCam live media orchestration stack:

1. Local RTMP/SRT ingestion keeps raw live media on the local network.
2. FFmpeg or GStreamer writes each feed into a rolling `/dev/shm` lookback buffer.
3. Faster-Whisper emits timestamped transcript events per stream.
4. Local rules and Gemma classify hype moments through environment-configured APIs.
5. OBS or PyVMIX switches the master output using buffered media from before the trigger.

The production architecture notes live in `../docs/ARCHITECTURE.md`. Shared event contracts for transcripts, hype signals, buffered clip requests, and switcher targets live in `src/contracts.py`.

## Project Structure

```text
ai-stream-director/
  src/
    contracts.py
    main.py
    obs_controller.py
    ai_director.py
    transcript_router.py
    scheduler.py
    config.py
  docker-compose.yml
  Dockerfile
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

Dry-run mode skips the OBS WebSocket connection and prints scene switches to the terminal instead.

The default Ollama model is:

```text
GEMMA_MODEL=gemma3:4b
GEMMA_API_URL=http://ollama:11434
OLLAMA_MODEL=gemma3:4b
OLLAMA_BASE_URL=http://ollama:11434
```

`GEMMA_*` names are preferred for the production architecture. `OLLAMA_*` names remain compatibility aliases for the current MVP. You can replace the model with another small local Gemma-compatible model if needed.

## Running With Docker Compose

Start the app:

```powershell
docker compose up --build app
```

On first run, Docker Compose will start Ollama and pull the configured model. That can take a while.

If terminal input feels awkward through `docker compose up`, run the app as an interactive one-off container:

```powershell
docker compose up -d ollama
docker compose run --rm ollama-pull
docker compose run --rm app
```

At startup, the app checks that the configured Gemma/Ollama endpoint is reachable and that `GEMMA_MODEL` appears in the model list. If the model is missing, pull it before starting the app:

```powershell
ollama pull gemma3:4b
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

If a transcript line prints `AI decision failed`, Ollama responded but did not produce a usable final decision object. Try the line again, use a lower-temperature model, or switch to a model that follows JSON instructions more reliably.

## Test Plan

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

## Running Without Docker

If you already have Ollama running locally:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
ollama pull gemma3:4b
$env:OBS_HOST="127.0.0.1"
$env:OBS_PORT="4455"
$env:OBS_PASSWORD="your-obs-websocket-password"
$env:DRY_RUN_OBS="true" # optional: skip OBS WebSocket for local smoke testing
$env:GEMMA_API_URL="http://127.0.0.1:11434"
python src/main.py
```

## Next Steps

The next implementation work is tracked in Tess tickets under `../tickets/` and
summarized in `../docs/ROADMAP.md`.

The most important near-term shift is replacing manual terminal transcript input
with timestamped `TranscriptEvent` objects while keeping the scheduler and OBS
controller mostly unchanged. After that, buffered switching can use
`LookbackClipRequest` to cut to media from before a trigger instead of switching
only to the live moment.
