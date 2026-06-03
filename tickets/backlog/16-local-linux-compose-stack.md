description: Create local Linux Docker Compose stack for production services
prereq: local-media-server-ingest, rolling-lookback-buffer, transcription-event-api, gemma-orchestration-adapter
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/docker-compose.yml, ai-stream-director/.env.example
----
The stack should be runnable on local Linux hardware with Docker Compose. It
should start the media server, buffer workers, transcription service, AI
endpoint, and orchestrator with environment-driven configuration.

Expected behavior:
- Keep heavy video ingress local.
- Mount `/dev/shm` or another RAM-backed buffer path for media segments.
- Allow AI endpoints to run locally or remotely by changing only environment
  values.
- Document startup, smoke test, shutdown, and recovery steps.
