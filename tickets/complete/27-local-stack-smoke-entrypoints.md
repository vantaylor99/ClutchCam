description: Completed no-player local Linux stack smoke entrypoints
prereq: local-linux-compose-profiles
files: ai-stream-director/scripts/smoke_media_server.py, ai-stream-director/scripts/smoke_buffer_worker.py, ai-stream-director/scripts/smoke_transcription_api.py, ai-stream-director/scripts/smoke_ai_endpoint.py, ai-stream-director/scripts/smoke_orchestrator_dry_run.py, ai-stream-director/scripts/__init__.py, ai-stream-director/tests/test_smoke_entrypoints.py, ai-stream-director/README.md
----
No-player smoke entrypoints now cover the local Linux runtime stack boundaries.

Completed behavior:

- `scripts/smoke_media_server.py` starts or targets the SRS media-server,
  waits for `/api/v1/summaries`, and can publish short generated FFmpeg RTMP
  sources.
- `scripts/smoke_buffer_worker.py` inspects `LOOKBACK_BUFFER_DIR`, summarizes
  segment metadata, and requires at least one resolvable lookback clip.
- `scripts/smoke_transcription_api.py` posts generated or configured audio to a
  Faster-Whisper-compatible `/transcribe` endpoint.
- `scripts/smoke_ai_endpoint.py` validates Ollama model availability or
  OpenAI-compatible endpoint reachability with optional bearer auth.
- `scripts/smoke_orchestrator_dry_run.py` runs `src/main.py` with
  `DRY_RUN_OBS=true`, bounded terminal input, and a fake local AI endpoint by
  default.
- The smoke scripts are import-safe and timeout-bound. Importing them does not
  start Docker, FFmpeg, SRS, OBS, HTTP clients, or runtime directories.
- `ai-stream-director/README.md` documents the local Linux smoke sequence,
  expected JSON/output fragments, skip/remote environment knobs, and shutdown.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_smoke_entrypoints -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest discover -s tests -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B scripts\smoke_orchestrator_dry_run.py
```

The smoke-entrypoint test suite passed 15/15, full discovery passed 150/150,
and the dry-run orchestrator smoke exited successfully with the expected OBS
dry-run/manual-command output.
