description: Add service health checks and structured orchestration logs
prereq: production-service-boundaries
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/src/main.py
----
The production stack needs clear health and event visibility across media
ingestion, buffering, transcription, AI, and switching. Logs should make it easy
to understand why a switch did or did not happen.

Expected behavior:
- Emit structured events for transcript receipt, model decisions, hype signals,
  clip requests, and switcher actions.
- Add health checks for local services where possible.
- Include stream ID and correlation IDs across related events.
- Preserve readable terminal output for the MVP path.
