description: Completed Windows local Ollama/Gemma dry-run quickstart docs
prereq: 
files: ai-stream-director/README.md
----
The README now documents the direct Windows PowerShell local-AI dry-run path.

Built:

- Added a `Windows Local AI Dry Run` section.
- Clarified that Docker, SRS, and OBS are not required for the terminal dry-run
  AI loop.
- Distinguished direct host execution at `http://127.0.0.1:11434` from Compose
  service DNS at `http://ollama:11434`.
- Included PowerShell setup commands for `.venv`, dependencies, Ollama,
  `gemma3:4b`, local `GEMMA_*`/`OLLAMA_*` env vars, `DRY_RUN_OBS=true`, and
  `python src/main.py`.
- Added a small pasteable transcript/manual-command script and expected dry-run
  result wording that tolerates model variation.

Validation:

- Read the quickstart end to end for URL consistency and PowerShell command
  order.
- `git diff --check` passed with only CRLF normalization warnings.
