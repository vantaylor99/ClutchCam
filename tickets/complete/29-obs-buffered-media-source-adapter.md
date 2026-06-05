description: Completed OBS adapter for resolved buffered media playback
prereq: buffered-switcher-playback
files: ai-stream-director/src/obs_controller.py, ai-stream-director/src/services/switcher.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_buffered_switcher.py, docs/ARCHITECTURE.md, ai-stream-director/README.md, docs/runbooks/local-linux-compose.md, docs/STATUS.md
----
Implemented an OBS media-source playback adapter for ready buffered switch
targets.

What changed:

- `OBSController` and `DryRunOBSController` now expose
  `set_media_source(source_name, media_uri)`.
- Real OBS mode maps `file://` URIs to local Media Source `local_file` settings
  and non-file URIs to network `input` settings.
- OBS settings are read back and verified before the scene cut; missing or
  mismatched readback fails clearly.
- `MediaSourceOutputSwitcher` updates the configured Media Source, then cuts to
  the target scene.
- Targets without resolved `media_uri` values are rejected without touching OBS.
- Existing `SceneOutputSwitcher` and dry-run scene behavior remain intact.
- Operator docs now describe the required pre-created OBS Media Source and path
  reachability expectations.

Validation:

- `C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B -m unittest tests.test_dry_run_obs tests.test_buffered_switcher tests.test_runtime_event_pipeline -v`
- Result: 48 tests passed.

Notes:

- The adapter is implemented and unit-tested, but the default terminal MVP path
  still uses immediate scene switching unless a runtime caller injects the
  media-source output switcher.
- Live OBS validation still needs to confirm the exact Media Source settings
  and clip path reachability on the OBS host.
