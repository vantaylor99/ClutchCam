description: Document a local Windows Ollama/Gemma dry-run quickstart
prereq: 
files: ai-stream-director/README.md, docs/STATUS.md, docs/ROADMAP.md
----
Local no-Docker testing uses host URLs such as `http://127.0.0.1:11434`, while
the Compose stack uses service DNS such as `http://ollama:11434`. During setup,
this difference caused the app to report that Ollama was unreachable at the
Compose hostname when it was being run directly from PowerShell.

Expected behavior:

- The README should include a short Windows local-AI quickstart:
  create/activate `.venv`, install requirements, install Ollama, pull
  `gemma3:4b`, set local `GEMMA_API_URL`/`OLLAMA_BASE_URL`, enable
  `DRY_RUN_OBS`, and run `python src/main.py`.
- The docs should make clear that Docker/SRS is not required for the terminal
  dry-run AI loop.
- The docs should make clear that `http://ollama:11434` is for Compose and
  `http://127.0.0.1:11434` is for direct host execution.
- The quickstart should include a tiny manual transcript script and the expected
  dry-run result.
