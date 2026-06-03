description: Document operator setup and failure recovery runbooks
prereq: local-linux-compose-stack
files: README.md, docs/STATUS.md, docs/ROADMAP.md, docs/ARCHITECTURE.md, ai-stream-director/README.md
----
The system will need clear operator documentation for local events and live
streaming sessions. Runbooks should cover setup, OBS scenes, stream publishing,
health checks, common failures, and recovery actions.

Expected behavior:
- Document OBS scene setup for MVP and buffered playback modes.
- Document how each player or capture machine publishes a stream.
- Include smoke-test commands for ingest, buffer, transcription, AI, and
  switching.
- Explain what to do when a stream, transcription service, AI endpoint, or OBS
  WebSocket connection fails.
