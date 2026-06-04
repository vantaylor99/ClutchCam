description: Add a Linux-safe rolling buffer worker runtime entrypoint
prereq: local-media-server-ingest, rolling-lookback-buffer
files: ai-stream-director/src/buffer_worker.py, ai-stream-director/tests/test_buffer_worker_entrypoint.py
----
The rolling lookback buffer implementation already exists behind
`services.buffer`, but there is no runtime process that starts it independently
from the terminal MVP. Add a small worker entrypoint that can run on the local
Linux host or inside Docker Compose and keep one FFmpeg segment writer per
stable stream ID alive.

The worker should load `AppConfig`, build `RollingBufferConfig.from_app_config`,
instantiate `FFmpegRollingLookbackBuffer`, and own process lifecycle:
startup validation, signal or keyboard shutdown, and cleanup through
`buffer.stop()`. It should not change the terminal orchestrator path in
`src/main.py`.

Linux runtime expectations:

- The default buffer root is `LOOKBACK_BUFFER_DIR=/dev/shm/clutchcam`.
- Inside Compose, the same host RAM-backed path should later be bind-mounted
  into containers that need to read resolved clips.
- The worker consumes service-DNS URLs such as
  `rtmp://media-server:1935/live/player_1` through the existing per-stream
  `LOOKBACK_INPUT_URL_*` configuration.
- Missing input URLs, an unwritable buffer directory, or a missing FFmpeg
  executable should fail clearly before the worker claims to be healthy.

Tests should stay fast and should not require Docker, FFmpeg, SRS, live RTMP/SRT
input, or writes to real `/dev/shm`. Use temporary directories and fake buffer
objects or monkey-patched process startup where needed.

TODO:

- Add `src/buffer_worker.py` with an import-safe main function and
  `if __name__ == "__main__"` entrypoint.
- Load `AppConfig` and construct the existing rolling buffer config without
  duplicating environment parsing.
- Add startup validation for configured stream IDs, buffer directory
  writability, and FFmpeg availability.
- Start `FFmpegRollingLookbackBuffer`, keep the worker process alive, and stop
  child FFmpeg processes on `SIGTERM`, `SIGINT`, and normal exit.
- Log one concise startup line per stream showing stream ID, input URL, and
  buffer directory.
- Add tests for config construction, validation failures, signal-safe cleanup,
  and no-import side effects.
- Run focused tests with bytecode disabled:
  `python -B -m unittest tests.test_buffer_worker_entrypoint tests.test_rolling_buffer -v`.
