description: Linux generated RTMP ingest acceptance evidence captured
prereq: docker-runtime-ffmpeg, buffer-worker-ffmpeg-supervision, generated-ingest-preflight-diagnostics
files: ai-stream-director/scripts/compose_generated_ingest_checkpoint.py, ai-stream-director/scripts/smoke_media_server.py, ai-stream-director/scripts/smoke_buffer_worker.py, ai-stream-director/docker-compose.yml, docs/STATUS.md, docs/ROADMAP.md, docs/runbooks/local-linux-compose.md
----
Live Linux generated-ingest validation was run on `clutchcam-media-1` against
Git revision `2f5f3fb` with evidence retained at:

```text
/home/vantaylor99/clutchcam-test-evidence-20260627T002508Z
```

Validated scope:

- Python unit suite passed on the Linux host: `249` tests.
- Docker Compose started `media-server` and `buffer-worker` with healthy service
  state after replacing the SRS healthcheck with an in-container pid check.
- One-stream generated RTMP publish passed for `player_1`; SRS summaries were
  reachable and the buffer resolved a ready lookback clip.
- Four-stream generated RTMP publish passed for `player_1`, `player_2`,
  `player_3`, and `player_4`; each stream independently had non-empty segment
  metadata, an existing latest segment, and a ready clip rooted under its own
  `/dev/shm/clutchcam/<stream_id>` directory.
- RAM-backed storage was confirmed with `findmnt`: `/dev/shm/clutchcam` is
  `tmpfs` and the worker bind mount maps that exact host path into the same
  container path.
- Ollama AI endpoint smoke passed after pulling `gemma3:4b`; the combined
  checkpoint passed for media-server, buffer, AI, and dry-run orchestrator.

Follow-up split out of this ticket:

- `buffer-reconnect-telemetry-proof` tracks the remaining strict reconnect
  evidence gap. A two-publish reconnect exercise kept the same buffer-worker
  container alive and advanced `player_1` segment sequence from `55` to `61`,
  but the previous log-based acceptance expected a `buffer_ffmpeg_exited`
  followed by a later `buffer_ffmpeg_started` event. Those exact log lines did
  not appear in the captured window, so reconnect proof needs clearer telemetry
  or a revised acceptance criterion.

