description: Completed Linux-safe rolling buffer worker runtime entrypoint
prereq: local-media-server-ingest, rolling-lookback-buffer
files: ai-stream-director/src/buffer_worker.py, ai-stream-director/tests/test_buffer_worker_entrypoint.py
----
The rolling lookback buffer now has an import-safe runtime entrypoint at
`ai-stream-director/src/buffer_worker.py`.

Built:

- Added `buffer_worker.build_buffer_config()` using `AppConfig` and
  `RollingBufferConfig.from_app_config`.
- Added startup validation for stream IDs, configured input URLs, FFmpeg
  executable resolution, and writable buffer root.
- Added `run_buffer_worker(...)` to start `FFmpegRollingLookbackBuffer`, block
  until shutdown, and always call `buffer.stop()`.
- Added stop handling for `SIGTERM`, `SIGINT`, `KeyboardInterrupt`, and normal
  exit while keeping the terminal orchestrator path untouched.
- Added concise per-stream startup logging with stream ID, input URL, and
  buffer directory.
- Confirmed importing `buffer_worker` does not create configured buffer
  directories, install signal handlers, or start subprocesses.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_buffer_worker_entrypoint tests.test_rolling_buffer -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_ai_director tests.test_dry_run_obs tests.test_buffer_worker_entrypoint tests.test_rolling_buffer tests.test_transcription_worker_entrypoint tests.test_transcription_runtime tests.test_transcription_event_api tests.test_telemetry tests.test_service_boundaries -v
```

Result:

- Focused buffer worker/rolling buffer suite: 21 tests passed.
- Combined review suite: 93 tests passed.
