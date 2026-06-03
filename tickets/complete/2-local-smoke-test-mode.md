description: Completed review of dry-run OBS mode for local testing without OBS
prereq: nonblocking-terminal-loop
files: ai-stream-director/src/config.py, ai-stream-director/src/obs_controller.py, ai-stream-director/src/main.py, ai-stream-director/.env.example, ai-stream-director/README.md, ai-stream-director/tests/test_dry_run_obs.py
----
Reviewed the `DRY_RUN_OBS` implementation for local smoke testing without an OBS WebSocket connection.

The app parses `DRY_RUN_OBS`, selects `DryRunOBSController` in `main.py`, and exposes the same scheduler-facing controller methods as the real OBS controller: `connect`, `set_scene`, and `get_current_scene`. In dry-run mode, OBS WebSocket setup is skipped, the current scene is tracked in memory, and scene switches print as `[DRY RUN OBS] Scene switch: ...`.

Added focused unit coverage in `ai-stream-director/tests/test_dry_run_obs.py` for:

- `DRY_RUN_OBS` defaulting to false.
- Common true values for `DRY_RUN_OBS`.
- Dry-run controller connection guards.
- Dry-run scene tracking after connect.
- Scheduler status and dry-run controller state after manual scene switches.

Review notes:

- Static inspection found the dry-run behavior consistent with the existing scheduler contract.
- README and `.env.example` document the new mode and local smoke-test path.
- `DRY_RUN_OBS=false` still selects the existing OBS WebSocket controller and connection error messaging.

Validation:

- Attempted `python -m unittest discover ai-stream-director/tests`, but this shell has no `python` executable on PATH.
- Also checked for `py`, `python3`, `uv`, `poetry`, `pip`, and `docker`; none are available in this shell.
- Tests should be run in an environment with Python installed using:

```powershell
cd ai-stream-director
python -m unittest discover tests
```
