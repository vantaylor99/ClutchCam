description: Document operator setup and failure recovery runbooks
prereq: local-linux-compose-stack
files: README.md, docs/STATUS.md, docs/ROADMAP.md, docs/ARCHITECTURE.md, docs/runbooks/, ai-stream-director/README.md
----
Create clear operator documentation for local events and live streaming
sessions. The runbooks should help a future operator start from a clean Linux
host or developer machine, validate each service boundary, and recover from
common failures without guessing which component is responsible.

Implementation scope:

- Add a docs/runbooks area if one does not exist.
- Document MVP terminal dry-run setup separately from local Linux Compose setup.
- Document OBS scene setup for immediate MVP switching and note the future
  buffered media-source adapter requirement.
- Document how each player/capture machine should publish RTMP/SRT streams to
  the local SRS service.
- Include smoke-test commands for media ingest, buffer, transcription API, AI
  endpoint, and orchestrator dry-run.
- Include failure/recovery guidance for missing streams, missing buffer
  segments, unavailable transcription service, unavailable AI endpoint, and OBS
  WebSocket problems.
- Keep the docs accurate about what is not yet implemented: real OBS buffered
  media-source playback, local Faster-Whisper Compose profile, and full
  end-to-end live Linux validation.

TODO:

- Add one or more concise runbook markdown files under `docs/runbooks/`.
- Link the runbook(s) from the root README and `ai-stream-director/README.md`.
- Update `docs/STATUS.md` only if the current status wording becomes stale.
- Run `git diff --check`.
