description: Add local RTMP/SRT ingestion service configuration
prereq: production-service-boundaries
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/docker-compose.yml, ai-stream-director/.env.example
----
The production stack needs a local media server layer so raw video feeds stay on
the local network. The first pass should select and configure an open-source
RTMP/SRT-capable server such as SRS or LiveKit in Docker Compose.

Expected behavior:
- Accept four stable stream inputs that map to `player_1` through `player_4`.
- Expose local URLs that FFmpeg buffer workers can consume.
- Keep ingest configuration local-first and environment-driven.
- Document how a player or capture machine should publish to the local server.
- Provide a smoke-test path that can use generated FFmpeg test sources instead
  of real players.
