description: Document a local Windows Ollama/Gemma dry-run quickstart
prereq: 
files: ai-stream-director/README.md, ai-stream-director/.env.example, ai-stream-director/src/config.py, docs/STATUS.md, docs/ROADMAP.md
----
The local terminal MVP can run directly from Windows PowerShell with host-local
Ollama and dry-run OBS. The documentation should make that path explicit so a
developer does not accidentally use Docker Compose service DNS such as
`http://ollama:11434` while running `python src/main.py` directly on the host.

Research notes:

- `ai-stream-director/README.md` already documents Setup, Terminal Input Format,
  Test Plan, Troubleshooting, Docker Compose, and a short Running Without Docker
  section.
- The current Running Without Docker section includes venv setup, dependency
  install, `ollama pull gemma3:4b`, `DRY_RUN_OBS=true`, and
  `GEMMA_API_URL=http://127.0.0.1:11434`.
- The direct-host section does not currently set the compatibility aliases
  `OLLAMA_BASE_URL` and `OLLAMA_MODEL`, and it does not provide a compact manual
  transcript script with expected dry-run output.
- `ai-stream-director/.env.example` defaults `GEMMA_API_URL` and
  `OLLAMA_BASE_URL` to `http://ollama:11434`, which is correct for Compose but
  misleading for direct host execution unless the README calls out the
  distinction.
- `ai-stream-director/src/config.py` prefers `GEMMA_API_URL` and `GEMMA_MODEL`
  while accepting `OLLAMA_BASE_URL` and `OLLAMA_MODEL` as compatibility aliases.
- `DRY_RUN_OBS=true` bypasses real OBS WebSocket setup, so Docker, SRS, and OBS
  are not required for the terminal dry-run AI loop.

The implementation should add a concise Windows local-AI quickstart to the
README, or reshape the existing Running Without Docker section into that
quickstart. It should clearly separate these URL contexts:

- Direct host execution from PowerShell: `http://127.0.0.1:11434`
- Docker Compose service-to-service execution: `http://ollama:11434`

The quickstart should cover creating and activating `.venv`, installing
requirements, installing or starting Ollama, pulling `gemma3:4b`, setting
host-local Gemma and Ollama environment variables, enabling `DRY_RUN_OBS`, and
running `python src/main.py`.

The quickstart should include a tiny pasteable manual transcript script for the
interactive terminal MVP. The expected result should make clear that the app
starts without Docker/SRS/OBS, reaches the host-local Ollama endpoint, accepts
manual transcript lines, and prints dry-run scene-switch output when a manual
command or high-confidence AI decision changes scenes.

TODO:

- Update `ai-stream-director/README.md` with a focused Windows local AI dry-run
  quickstart near Setup, Test Plan, or Running Without Docker.
- Include PowerShell commands for `.venv` creation/activation, dependency
  install, `ollama pull gemma3:4b`, host-local `GEMMA_API_URL` and
  `OLLAMA_BASE_URL`, model names, `DRY_RUN_OBS=true`, and `python src/main.py`.
- State that Docker and SRS are not required for the terminal dry-run AI loop.
- State that `http://ollama:11434` is for Compose and
  `http://127.0.0.1:11434` is for direct host execution.
- Add a small pasteable transcript/manual-command script and expected dry-run
  result. Keep any AI-dependent result phrasing tolerant of model variation.
- Update `docs/STATUS.md` or `docs/ROADMAP.md` only if the README change alters
  project status or ticket-map bookkeeping.
- Validate the edited docs by reading the quickstart end to end for PowerShell
  syntax, URL consistency, and no accidental requirement for Docker/SRS/OBS.
