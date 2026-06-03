description: Completed review of Ollama readiness checks and AI JSON hardening
prereq: local-smoke-test-mode
files: ai-stream-director/src/ai_director.py, ai-stream-director/src/main.py, ai-stream-director/tests/test_ai_director.py, ai-stream-director/README.md
----
Reviewed the Ollama readiness and JSON parsing hardening.

The implementation now checks Ollama startup readiness through `/api/tags`, fails before OBS connection when Ollama is unavailable or the configured model is missing, and reports model recovery with an `ollama pull <model>` command. Runtime Ollama generation failures are surfaced through `AIDirectorError`, while unexpected exceptions remain separately reported.

AI decision parsing accepts decoded response objects, markdown-fenced JSON, short surrounding text around a JSON object, and trailing commas before closing braces or brackets. It still rejects array-shaped decisions, missing Ollama `response` fields, and unsupported scene names are normalized back to `Quad View`.

Review follow-up:
- Hardened `/api/tags` handling so a valid JSON response with the wrong top-level shape raises `AIDirectorError` instead of leaking `AttributeError`.
- Added a unit test covering the unexpected `/api/tags` response shape.

Validation notes:
- Inspected `ai-stream-director/src/ai_director.py`, `ai-stream-director/src/main.py`, `ai-stream-director/src/scheduler.py`, `ai-stream-director/src/config.py`, `ai-stream-director/tests/test_ai_director.py`, and `ai-stream-director/README.md`.
- Could not run `python -m unittest discover -s tests`: no `python`, `py`, or `python3` command is available in this shell.
- Could not run containerized validation: no `docker` command is available in this shell.

Suggested out-of-band checks:
- Run `python -m unittest discover -s tests` from `ai-stream-director/` in an environment with Python installed.
- Smoke test startup with Ollama stopped, with Ollama running but `OLLAMA_MODEL` missing, and with `OLLAMA_MODEL` installed.
- Send transcript lines that lead the local model to return fenced JSON, JSON with surrounding text, and JSON with trailing commas, and confirm accepted decisions still flow to the scheduler.
