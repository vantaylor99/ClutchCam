description: Allow dry-run mode to start without obsws-python installed
prereq: 
files: ai-stream-director/src/obs_controller.py, ai-stream-director/src/main.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/README.md
----
`DRY_RUN_OBS=true` skips the real OBS WebSocket connection, but importing
`main.py` imports `obs_controller.py`, which imports `obsws_python` at module
import time. A dry-run-only local smoke test therefore fails before dry-run mode
can help if the OBS WebSocket dependency is missing.

Expected behavior:

- Dry-run mode should be able to start and import without `obsws-python`
  installed.
- Real OBS mode should still fail clearly if `obsws-python` is missing.
- The real OBS dependency should be loaded lazily, only when constructing or
  using `OBSController`.
- Existing dry-run and service-boundary tests should keep passing.
- README setup notes should explain the dependency behavior if the dependency
  split changes.

Implementation notes:

- Move `import obsws_python as obs` out of `obs_controller.py` module scope and
  into the real OBS controller path.
- Keep `DryRunOBSController` standard-library-only.
- Add a test that simulates missing `obsws_python` while importing/using dry-run
  code. Use mocking/import isolation rather than uninstalling dependencies.

TODO:

- Add a dry-run import/start test that does not require `obsws_python`.
- Make real OBS dependency import lazy and error clearly in real OBS mode.
- Update docs if the setup/dependency story changes.
- Run targeted dry-run tests and the full unit suite.
- Move this ticket to `review/` with validation notes.
