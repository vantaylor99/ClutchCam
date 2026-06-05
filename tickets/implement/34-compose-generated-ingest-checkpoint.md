description: Add opt-in Docker Compose generated-ingest checkpoint
prereq: local-checkpoint-smoke-runner
files: ai-stream-director/scripts/, ai-stream-director/docker-compose.yml, ai-stream-director/README.md, ai-stream-director/tests/test_compose_generated_ingest_checkpoint.py, docs/runbooks/local-linux-compose.md
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

TODO:

- Add an import-safe script that orchestrates the existing media-server and
  buffer smoke helpers for generated-ingest validation.
- Make the script opt-in and timeout-bound; it must never run Docker/FFmpeg on
  import.
- Add unit tests using mocked compose/media/buffer boundaries.
- Include JSON report fields for compose command, published streams, buffer
  readiness, failure reason, and operator hints.
- Document the command in the local Linux Compose runbook.
