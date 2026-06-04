description: Expose runtime health checks for local and containerized services
prereq: health-check-primitives, local-linux-compose-profiles
files: ai-stream-director/src/services/health.py, ai-stream-director/src/buffer_worker.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/main.py, ai-stream-director/docker-compose.yml
----
Health-check primitives exist, but runtime services do not yet expose consistent
operator-facing health commands or container healthchecks.

Expected behavior:
- Add bounded healthcheck commands or endpoints for the media server, buffer
  worker, transcription worker, AI endpoint, and orchestrator boundary.
- Keep checks environment-driven so local Linux and cloud VM deployments use the
  same contract.
- Make Docker Compose healthchecks call the same lightweight checks where
  practical.
- Ensure health failures return clear degraded/unhealthy reasons for operators.

TODO:

- Inspect existing `services.health` and worker entrypoints before choosing the
  smallest runtime surface.
- Add import-safe healthcheck helpers or CLI commands for buffer worker,
  transcription worker, AI endpoint, and orchestrator readiness.
- Add Docker Compose `healthcheck` blocks where they can run without side
  effects or long waits.
- Add unit tests that mock filesystem, HTTP, and subprocess boundaries.
- Keep checks bounded and deterministic; no test may require Docker, FFmpeg,
  SRS, OBS, Ollama, Faster-Whisper, GPUs, or network access.
- Run focused tests covering health checks and Compose healthcheck declarations.
