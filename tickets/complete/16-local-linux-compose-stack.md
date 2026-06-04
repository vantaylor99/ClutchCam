description: Completed local Linux Compose stack baseline
prereq: local-media-server-ingest, rolling-lookback-buffer, transcription-event-api, gemma-orchestration-adapter
files: ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/scripts/, ai-stream-director/README.md, docs/ARCHITECTURE.md, docs/ROADMAP.md
----
The local Linux Compose stack baseline is now represented by focused completed
tickets and runtime smoke tooling.

Completed behavior:

- `media-server`, `buffer-worker`, `transcription-worker`, `orchestrator`, and
  optional `local-ai` profiles exist in `ai-stream-director/docker-compose.yml`.
- SRS provides the local RTMP/SRT media-server surface.
- Buffer and transcription workers have container entrypoints.
- `/dev/shm` host bind mounts are documented through
  `LOOKBACK_BUFFER_HOST_DIR` and `AUDIO_EXTRACT_HOST_DIR`.
- AI and transcription boundaries remain environment-driven through
  `GEMMA_API_URL`, `AI_PROVIDER`, `GEMMA_MODEL`, `GEMMA_API_KEY`, and
  `TRANSCRIPTION_API_URL`.
- No-player smoke scripts cover media-server, buffer-worker, transcription API,
  AI endpoint, and dry-run orchestrator checks.

Remaining work has been split into narrower follow-up tickets:

- `tickets/backlog/31-faster-whisper-compose-profile.md` covers an optional
  local Faster-Whisper API service profile.
- `tickets/backlog/32-runtime-healthcheck-entrypoints.md` covers concrete
  runtime healthcheck commands/endpoints.
- `tickets/backlog/18-operator-runbooks.md` covers operator setup and recovery
  documentation.
