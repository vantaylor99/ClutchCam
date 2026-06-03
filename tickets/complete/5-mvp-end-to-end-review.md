description: Reviewed and validated the AI Stream Director MVP end to end
prereq: nonblocking-terminal-loop, local-smoke-test-mode, ollama-readiness-and-json-hardening, obs-connection-and-scene-validation
files: ai-stream-director/src/scheduler.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/docker-compose.yml, ai-stream-director/tests/test_ingestion_config.py, ai-stream-director/README.md, README.md, docs/ROADMAP.md, docs/STATUS.md
----
The terminal MVP review is complete. The core app remains understandable and
well separated across terminal input, transcript history, AI decision parsing,
scheduler rules, and OBS control. The production service boundary modules stay
import-safe and are still separate from runtime OBS, AI, media-server, FFmpeg,
and transcription startup.

Two review fixes landed:

- Startup now initializes `Quad View` without consuming the first AI cooldown
  window, so an immediate high-confidence player moment after launch can switch
  correctly.
- The Compose `ollama-pull` service now prefers `GEMMA_MODEL` before falling
  back to `OLLAMA_MODEL`, matching the documented config precedence and app
  readiness check.

Regression coverage was added for first AI focus after startup, automatic
return to `Quad View` without terminal input, and the Compose model-pull
precedence.

Documentation was checked against the app behavior. The AI Stream Director
README matches the current dry-run, OBS-scene, terminal-command, Ollama/Gemma,
and setup behavior. Root status/roadmap docs now distinguish implemented ingest
and rolling-buffer building blocks from the still-unwired runtime director path,
and mark the terminal MVP review complete.

Validation:

- `python -m unittest tests.test_contracts tests.test_ingestion_config tests.test_rolling_buffer tests.test_service_boundaries -v` passed: 32 tests.
- Full unittest discovery was run through in-memory stubs for the two declared
  runtime packages missing from this Python environment (`requests` and
  `obsws-python`); all 54 tests passed.
- A deterministic dry-run terminal-loop smoke harness passed for calm transcript
  input, a Player 3 focus moment, cooldown rejection of an immediate Player 4
  moment, manual `/p4` and `/quad`, `/ai off`, `/ai on`, `/status`, `/quit`, and
  automatic return to `Quad View`.
- `python -m py_compile src/scheduler.py tests/test_dry_run_obs.py tests/test_ingestion_config.py`
  passed for the changed Python files.

Validation limitations and remaining risks:

- Native `python -m unittest discover -s tests -v` could not complete in this
  runner because the active Python environment does not have `requests` or
  `obsws-python` installed. The repo documents that full-suite validation
  requires `pip install -r requirements.txt`.
- `docker compose config` could not be run because Docker is not installed in
  this environment.
- A live OBS WebSocket scene-switching trial was not possible here. The first
  real OBS trial should create the five documented scenes exactly and verify
  startup validation plus live `/quad`, `/p1` through `/p4`, and AI-driven focus
  switching.
