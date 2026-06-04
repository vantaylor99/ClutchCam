description: Completed runtime health-check entrypoints
prereq: health-check-primitives, local-linux-compose-profiles
files: ai-stream-director/src/services/health.py, ai-stream-director/src/buffer_worker.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/main.py, ai-stream-director/docker-compose.yml, ai-stream-director/tests/test_runtime_healthcheck_entrypoints.py, ai-stream-director/tests/test_linux_compose_stack.py
----
Runtime services now expose bounded health checks for local Linux and
containerized operation.

Built:

- Expanded `services.health` with runtime health targets for `media-server`,
  `buffer-worker`, `transcription-worker`, `ai-endpoint`, and `orchestrator`.
- Added checks for HTTP dependencies, executable resolution, configured stream
  inputs, writable runtime directories, required values, and OBS port range.
- Added `python -m services.health <target>` JSON reporting with an exit code
  that is zero only when the target is healthy.
- Added `--healthcheck` to `buffer_worker`, `transcription_worker`, and
  `src/main.py` so health probes do not construct or start the long-running
  runtime workers.
- Added Docker Compose healthchecks for SRS, the buffer worker, the
  transcription worker, and the orchestrator.
- Added unit coverage for health report shape, entrypoint short-circuiting, and
  Compose healthcheck definitions.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_runtime_healthcheck_entrypoints tests.test_health_checks tests.test_linux_compose_stack tests.test_buffer_worker_entrypoint tests.test_transcription_worker_entrypoint tests.test_service_boundaries -v
```

Result:

- Focused health/runtime suite: 60 tests passed.

Also verified:

```powershell
cd ai-stream-director\src
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m services.health --help
```

The health CLI prints the available target list and exits successfully.
