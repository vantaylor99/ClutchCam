description: Add optional local Faster-Whisper service profile
prereq: transcription-event-api, linux-compose-profiles
files: ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/README.md, ai-stream-director/tests/test_linux_compose_stack.py, docs/ARCHITECTURE.md, docs/runbooks/local-linux-compose.md
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

TODO:

- Add a disabled-by-default Compose profile for a Faster-Whisper-compatible API
  service with env-overridable image/model/device settings.
- Preserve `TRANSCRIPTION_API_URL` as the only app-facing endpoint contract.
- Keep local and remote endpoint examples in `.env.example`.
- Add tests that assert the profile is opt-in and not part of the default local
  Linux profile.
- Document CPU/GPU tradeoffs and recovery steps in the README/runbook.
