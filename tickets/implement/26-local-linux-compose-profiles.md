description: Add local Linux Docker Compose profiles for runtime services
prereq: buffer-worker-runtime-entrypoint, transcription-worker-runtime-entrypoint
files: ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/tests/test_linux_compose_stack.py
----
The current Compose file starts SRS, Ollama, an Ollama model-pull helper, and
the terminal `app` service. It hard-depends on local Ollama, which is useful for
the MVP but too rigid for the local Linux runtime stack where inference or
transcription may be remote GPU services selected by environment variables.

Add first practical Compose profiles for the local Linux stack:

- `media-server` runs on the local Linux host and accepts RTMP/SRT feeds.
- `buffer-worker` runs on the same local Linux host and writes rolling media
  segments to RAM-backed storage.
- `transcription-worker` runs on the same local Linux host and writes audio
  chunks to RAM-backed storage while calling the configured transcription API.
- `orchestrator` runs the current app/orchestration entrypoint and keeps OBS
  access environment-driven.
- Optional local AI remains `ollama` plus `ollama-pull` behind a profile such
  as `local-ai`.

The stack must preserve endpoint portability. `GEMMA_API_URL` and
`TRANSCRIPTION_API_URL` should be plain environment contracts: they can point at
Compose service DNS names for local containers or at remote endpoints without
changing Python code. Do not make `orchestrator` or workers require local
Ollama when `GEMMA_API_URL` points elsewhere.

Linux storage expectations:

- Use host RAM-backed bind mounts for paths that must be shared across
  containers, especially `/dev/shm/clutchcam` and
  `/dev/shm/clutchcam-audio`.
- Avoid Docker named volumes for continuously written media/audio chunks because
  named volumes are not guaranteed to be RAM-backed.
- Keep `ollama-data` as persistent model storage because model cache is not a
  short-lived media buffer.

This ticket should not choose an unvetted third-party Faster-Whisper server
image. It should make the transcription API endpoint explicit and overrideable;
a later ticket can add a concrete local STT server service if the project
chooses one.

TODO:

- Split the current all-in-one Compose behavior into profiles suitable for
  local Linux runtime startup and focused service smoke tests.
- Add `buffer-worker`, `transcription-worker`, and `orchestrator` services using
  the repo image build and the worker entrypoints from prerequisite tickets.
- Keep `media-server` service DNS as the default worker ingest endpoint:
  `rtmp://media-server:1935/live`.
- Move local Ollama and model pull into an optional local-AI profile while
  preserving current MVP defaults when that profile is used.
- Bind-mount Linux RAM-backed buffer and audio directories so producer and
  consumer containers see the same files.
- Extend `.env.example` with profile-oriented settings and comments for local
  versus remote `GEMMA_API_URL` and `TRANSCRIPTION_API_URL`.
- Add Compose config tests that inspect service names, profiles, dependencies,
  environment defaults, and `/dev/shm` bind mounts without requiring Docker to
  be installed.
- Run focused tests with bytecode disabled:
  `python -B -m unittest tests.test_linux_compose_stack tests.test_ingestion_config -v`.
