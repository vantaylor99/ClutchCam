description: Add optional local Faster-Whisper service profile
prereq: transcription-event-api, linux-compose-profiles
files: ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/README.md, docs/ARCHITECTURE.md
----
The transcription worker can call a Faster-Whisper-compatible HTTP API, but the
Compose stack currently assumes that endpoint exists outside the repo. Local
Linux testing should have an optional profile for running the transcription API
locally when hardware allows it.

Expected behavior:
- Add an opt-in Compose profile for a Faster-Whisper-compatible service or a
  documented local adapter container.
- Keep `TRANSCRIPTION_API_URL` as the only contract consumed by app logic.
- Allow the service to run locally or be replaced by a remote/cloud endpoint by
  changing environment values.
- Document GPU/CPU tradeoffs and startup checks without making the default unit
  suite depend on the container.
