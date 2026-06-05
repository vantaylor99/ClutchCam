# Operator Runbooks

These runbooks cover the current ClutchCam MVP operations path.

- [Terminal dry-run MVP](terminal-dry-run.md): run the orchestrator from a
  developer machine without OBS, Docker, SRS, or real capture feeds.
- [Local Linux Compose stack](local-linux-compose.md): bring up local SRS,
  publish player streams, run service smoke checks, and recover common event
  failures.
- [Linux and cloud deployment topology](linux-cloud-deployment-topology.md):
  choose host-local, two-Linux-host, or future cloud GPU endpoint layouts while
  preserving the current service contracts.

Current limits:

- The terminal MVP still consumes typed transcript lines.
- OBS switching is immediate scene switching against manually prepared scenes.
- Real OBS buffered media-source playback from resolved lookback clips is not
  implemented yet.
- Full end-to-end live Linux validation with SRS, FFmpeg, transcription, AI, and
  OBS remains future work.

Related docs:

- [AI Stream Director README](../../ai-stream-director/README.md)
- [Architecture](../ARCHITECTURE.md)
- [Current status](../STATUS.md)
