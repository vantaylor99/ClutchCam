description: Switch output using resolved buffered clip requests
prereq: buffer-clip-resolver, gemma-orchestration-adapter
files: ai-stream-director/src/contracts.py, ai-stream-director/src/services/switcher.py, ai-stream-director/src/obs_controller.py, ai-stream-director/src/scheduler.py, ai-stream-director/tests/test_buffered_switcher.py, ai-stream-director/tests/test_service_boundaries.py
----
Move the switching boundary beyond immediate live scene changes by adding a
buffer-aware switch path. When a positive trigger identifies a stream and time,
the switcher should be able to request a lookback clip, resolve it against the
buffer, and switch the output to either the ready buffered media target or a
clear pending/rejected result.

OBS remains the MVP target, but the implementation should keep buffered playback
behind service-level protocols so PyVMIX or a dedicated compositor can be added
later.

Implementation scope for this ticket:

- Keep the existing terminal `SceneScheduler.apply_ai_decision(...)` behavior
  working for immediate live scene changes.
- Add reusable helpers/classes under `services.switcher` that convert a
  stream-focused signal/target into a `LookbackClipRequest`.
- Add a buffer-backed switcher adapter that accepts a `LookbackBuffer`, resolves
  a `LookbackClipRequest`, and returns `SwitchResult` with `APPLIED`,
  `PENDING`, or `REJECTED`.
- Preserve manual override behavior and cooldown/focus rules in `scheduler.py`.
- Do not require live OBS, PyVMIX, FFmpeg, Docker, or real media in tests.
- If OBS-specific media-source mutation is too large for this pass, keep the
  first adapter at the boundary level and explicitly document what a later OBS
  media-source adapter must do.

TODO:

- Add focused tests for ready, pending, unavailable, and unknown-stream buffered
  switch outcomes.
- Add tests proving `LookbackClipRequest` uses `SWITCH_LOOKBACK_SECONDS` style
  pre-roll defaults and trigger time.
- Add tests proving immediate scene switching still works.
- Add or extend service-boundary tests for `SwitchResult` and buffered targets.
- Keep import boundaries clean: `services.switcher` must not import OBS clients,
  runtime workers, Docker, or requests.
- Run focused tests with bytecode disabled:
  `python -B -m unittest tests.test_buffered_switcher tests.test_service_boundaries tests.test_dry_run_obs -v`.
