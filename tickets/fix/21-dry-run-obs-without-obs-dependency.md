description: Allow dry-run mode to start without obsws-python installed
prereq: 
files: ai-stream-director/src/obs_controller.py, ai-stream-director/src/main.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/README.md
----
`DRY_RUN_OBS=true` skips the real OBS WebSocket connection, but importing
`main.py` still imports `obs_controller.py`, which imports `obsws_python` at
module import time. A Python-only dry-run smoke test therefore fails before the
dry-run path can help unless `obsws-python` is installed.

Expected behavior:

- Dry-run mode should be able to start without `obsws-python` installed.
- Real OBS mode should still fail clearly if the OBS WebSocket dependency is
  missing.
- Service-boundary import tests should continue proving runtime dependencies
  are not pulled into modules that should stay lightweight.
- README setup notes should distinguish optional dry-run-only dependencies from
  dependencies needed for real OBS control if the dependency split changes.
