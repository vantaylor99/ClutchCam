description: Completed operator setup and failure recovery runbooks
prereq: local-linux-compose-stack
files: README.md, docs/STATUS.md, docs/runbooks/README.md, docs/runbooks/terminal-dry-run.md, docs/runbooks/local-linux-compose.md, ai-stream-director/README.md
----
Operator documentation now covers the current MVP setup and local stack
boundaries.

Completed docs:

- `docs/runbooks/README.md` indexes the operator runbooks and states current
  limits.
- `docs/runbooks/terminal-dry-run.md` covers developer-machine setup,
  host-local Ollama or fake-AI dry-run, optional immediate OBS scene switching,
  AI and orchestrator smoke tests, and recovery for AI or OBS failures.
- `docs/runbooks/local-linux-compose.md` covers Linux Compose setup, SRS
  exposure choices, RTMP/SRT player publishing, OBS scene setup for immediate
  switching, smoke tests for media-server, buffer, transcription API, AI
  endpoint, and orchestrator dry-run.
- Failure recovery guidance now covers missing streams, missing buffer
  segments, unavailable transcription service, unavailable AI endpoint, OBS
  WebSocket issues, and currently unavailable buffered OBS playback.
- Root `README.md` and `ai-stream-director/README.md` point operators to the
  runbooks.
- `docs/STATUS.md` no longer lists operator runbooks as missing while keeping
  full production deployment docs and full live Linux validation as future work.

Accuracy notes:

- Real OBS buffered media-source playback is documented as future work.
- The local Faster-Whisper Compose profile is documented as future work.
- Full end-to-end live Linux validation is documented as future work.

Validation:

```powershell
git diff --check
```

Markdown link targets were checked during implementation.
