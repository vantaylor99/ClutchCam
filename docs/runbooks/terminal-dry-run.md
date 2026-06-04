# Terminal Dry-Run MVP Runbook

Use this path to validate the operator loop on a developer machine. It does not
require OBS, Docker, SRS, capture machines, or real audio/video streams.

## What This Runs

The dry-run starts `ai-stream-director/src/main.py`, forces
`DRY_RUN_OBS=true`, accepts terminal transcript lines, and prints simulated OBS
scene switches. It still exercises transcript routing, AI readiness, AI
decisions, cooldowns, manual commands, and return-to-quad timing.

Real buffered OBS media-source playback is not part of this path. The app does
not preload or replace OBS media sources with lookback-buffer clip URIs yet.

## Setup

From the repo root:

```powershell
Set-Location ai-stream-director
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

For a host-local Ollama run:

```powershell
ollama pull gemma3:4b
$env:DRY_RUN_OBS="true"
$env:AI_PROVIDER="ollama"
$env:GEMMA_API_URL="http://127.0.0.1:11434"
$env:GEMMA_MODEL="gemma3:4b"
python src/main.py
```

For a fully bounded dry-run that does not need a real AI endpoint:

```powershell
python scripts/smoke_orchestrator_dry_run.py
```

## Operator Inputs

After the prompt appears, use transcript lines and manual commands:

```text
/status
player_1: I am walking through the forest
player_3: no way, I just found something crazy
/p2
/quad
/ai off
/ai on
/quit
```

Expected dry-run output includes:

- `DRY_RUN_OBS enabled`
- `[DRY RUN OBS] Starting scene: Quad View`
- `[DRY RUN OBS] Scene switch: ...` for manual or accepted AI switches
- `Manual command applied.` after commands such as `/p2` or `/quad`

## Optional Real OBS Check

Only turn off dry-run when OBS is installed and you want to validate immediate
scene switching.

Create these OBS scenes manually, with exact names:

- `Quad View`
- `Player 1 Fullscreen`
- `Player 2 Fullscreen`
- `Player 3 Fullscreen`
- `Player 4 Fullscreen`

In OBS, enable `Tools > WebSocket Server Settings`, keep or set port `4455`,
and copy the password into the environment:

```powershell
$env:DRY_RUN_OBS="false"
$env:OBS_HOST="127.0.0.1"
$env:OBS_PORT="4455"
$env:OBS_PASSWORD="<obs-websocket-password>"
python src/main.py
```

The current OBS controller validates scene names and switches scenes
immediately. Each scene must already contain the sources you want on program.
For buffered playback, a future adapter must update or preload an OBS media
source with the resolved buffer URI before switching.

## Smoke Tests

AI endpoint smoke, Ollama provider:

```powershell
$env:AI_PROVIDER="ollama"
$env:GEMMA_API_URL="http://127.0.0.1:11434"
$env:GEMMA_MODEL="gemma3:4b"
python scripts/smoke_ai_endpoint.py
```

AI endpoint smoke, OpenAI-compatible provider:

```powershell
$env:AI_PROVIDER="openai-compatible"
$env:GEMMA_API_URL="https://gemma-gpu.example.internal/v1/chat/completions"
$env:GEMMA_MODEL="google/gemma-3-4b-it"
$env:GEMMA_API_KEY="<token>"
python scripts/smoke_ai_endpoint.py
```

Orchestrator dry-run smoke:

```powershell
python scripts/smoke_orchestrator_dry_run.py
```

## Failure And Recovery

AI endpoint unavailable:

- Symptom: startup reports that the AI director is not ready, or
  `smoke_ai_endpoint.py` exits non-zero.
- Recover: start Ollama or the remote OpenAI-compatible server, check
  `GEMMA_API_URL`, check `GEMMA_MODEL`, and for Ollama run
  `ollama pull <model>`.
- During an event, use `/ai off` and manual commands such as `/p1` and `/quad`
  until the endpoint is healthy.

OBS WebSocket issue:

- Symptom: startup cannot connect to OBS, reports an authentication error, or
  lists missing scenes.
- Recover: enable OBS WebSocket, verify `OBS_HOST`, `OBS_PORT`, and
  `OBS_PASSWORD`, then confirm all five required scene names match exactly.
- For operator training or non-OBS smoke tests, set `DRY_RUN_OBS=true`.

Unexpected or noisy AI choices:

- Symptom: the app switches to an unwanted player or ignores a desired moment.
- Recover: use `/quad` or `/pN` for an immediate manual override, use `/ai off`
  for manual-only operation, and use `/status` to confirm the current scene and
  AI state.

Buffered playback missing:

- Symptom: an operator expects the switch to cut to media from before the
  trigger.
- Recover: this is not implemented yet. The current MVP only performs immediate
  scene switches; real OBS buffered media-source playback remains future work.
