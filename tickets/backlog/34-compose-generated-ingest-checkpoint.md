description: Add opt-in Docker Compose generated-ingest checkpoint
prereq: local-checkpoint-smoke-runner
files: ai-stream-director/scripts/, ai-stream-director/docker-compose.yml, ai-stream-director/README.md, docs/runbooks/local-linux-compose.md
----
After the one-command smoke runner exists, add an opt-in checkpoint that uses
real Docker Compose, SRS, FFmpeg generated RTMP input, and the buffer worker to
prove that a synthetic player stream produces resolvable lookback clips on a
local Linux host.

Expected behavior:
- Start or target the `media-server` and `buffer-worker` Compose services.
- Publish one or more generated RTMP streams with bounded FFmpeg commands.
- Wait for buffer metadata and resolve a lookback clip for at least one stream.
- Emit a structured report that is useful when a Linux host, port, `/dev/shm`,
  or FFmpeg configuration is wrong.
- Keep this out of the default Python unit suite because it requires Docker and
  real media processes.
