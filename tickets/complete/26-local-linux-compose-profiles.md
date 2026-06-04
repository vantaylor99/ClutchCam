description: Completed local Linux Docker Compose runtime profiles
prereq: buffer-worker-runtime-entrypoint, transcription-worker-runtime-entrypoint
files: ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/tests/test_linux_compose_stack.py
----
The local Linux Compose stack now exposes profile-scoped runtime services.

Built:

- Added `media-server` profile for local SRS RTMP/SRT ingest.
- Added `buffer-worker` profile using the repo image and
  `python -m buffer_worker`.
- Added `transcription-worker` profile using the repo image and
  `python -m transcription_worker`.
- Added `orchestrator` profile for the current terminal orchestration entrypoint.
- Moved Ollama and model pulling behind an optional `local-ai` profile.
- Preserved endpoint portability through `GEMMA_API_URL`,
  `TRANSCRIPTION_API_URL`, and Linux `host.docker.internal` host-gateway
  mapping.
- Added `/dev/shm` bind mounts for media and audio buffers through
  `LOOKBACK_BUFFER_HOST_DIR` and `AUDIO_EXTRACT_HOST_DIR`.
- Kept only `ollama-data` as a Docker named volume because model cache is
  persistent storage rather than short-lived media/audio buffering.
- Avoided adding an unvetted Faster-Whisper image; transcription remains an
  explicit endpoint contract.
- Extended `.env.example` with Compose profile, RAM-backed storage, provider,
  and portable endpoint examples.
- Added Docker-free Compose text tests.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_linux_compose_stack tests.test_ingestion_config -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_ai_director tests.test_dry_run_obs tests.test_linux_compose_stack tests.test_ingestion_config -v
```

Result:

- Focused Compose/ingestion suite: 13 tests passed.
- Post-review AI/dry-run/Compose/ingestion suite: 58 tests passed.
