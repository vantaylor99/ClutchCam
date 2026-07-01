description: Completed review of the real OBS connection preflight and hardened its smoke output
files: ai-stream-director/scripts/smoke_obs_connection.py, ai-stream-director/src/obs_controller.py, ai-stream-director/src/main.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_smoke_entrypoints.py
----
Reviewed the real OBS connection-only preflight and the shared scene-validation
path used by the orchestrator.

## Review findings

- Checked the preflight call graph end to end. The shared helpers only read OBS
  version, current program scene, and scene list before any orchestrator scene
  switch can happen; they do not call scene-switch or media-source mutation
  methods.
- Confirmed secret handling stays redacted. The smoke result reports only
  `password_configured`, and failure messages never include the configured OBS
  password value.
- Confirmed failure semantics stay clear and nonzero for dry-run rejection,
  OBS connection or auth failures, and missing required scenes. The
  orchestrator still skips scene validation in dry-run mode and still fails
  early when required live scenes are missing.
- Fixed one minor review finding inline: the OBS smoke script now suppresses
  `OBSController.connect()` banner logs so stdout stays machine-readable JSON
  like the other smoke entrypoints.
- Fixed an additional live CLI finding: the no-argument command path now snapshots
  the real process environment before applying it, so shell-provided values such
  as `OBS_HOST`, `OBS_PORT`, and `DRY_RUN_OBS` are honored.
- Fixed an additional live CLI finding: third-party `obsws-python` connection
  chatter is suppressed during the smoke preflight, so unreachable OBS failures
  produce the script's single clean error line instead of a raw traceback.
- Added regression coverage proving the preflight path stays read-only and that
  controller logs/client output stay suppressed during the OBS smoke run.
- Major findings: none after the inline hardening above.
- Tripwires: none.

Validation from `C:\ClutchCam\ai-stream-director`:

```powershell
python -m unittest tests.test_smoke_entrypoints tests.test_dry_run_obs
python -m unittest discover -s tests -p "test*.py"
python -m py_compile scripts/smoke_obs_connection.py src/obs_controller.py src/main.py tests/test_dry_run_obs.py tests/test_smoke_entrypoints.py
git diff --check -- ai-stream-director/scripts/smoke_obs_connection.py ai-stream-director/src/obs_controller.py ai-stream-director/src/main.py ai-stream-director/tests/test_dry_run_obs.py ai-stream-director/tests/test_smoke_entrypoints.py
```

Results:

- 68 focused OBS preflight and smoke tests passed after the live CLI hardening.
- 342 unit tests passed in the broader suite.
- The changed Python entrypoints and tests compiled successfully.
- `git diff --check` passed; Git only reported the repository's existing LF/CRLF
  conversion warnings.
