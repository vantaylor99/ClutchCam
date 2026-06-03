description: Switch OBS or PyVMIX using buffered clip requests
prereq: buffer-clip-resolver, gemma-orchestration-adapter
files: docs/ARCHITECTURE.md, ai-stream-director/src/contracts.py, ai-stream-director/src/obs_controller.py, ai-stream-director/src/scheduler.py
----
The switcher layer should move beyond immediate live scene changes. When the AI
layer emits a positive trigger, the switcher should request buffered media for
the target stream beginning at `trigger_time - SWITCH_LOOKBACK_SECONDS` and
transition the master output to that clip or scene.

OBS remains the MVP target, but the interface should leave room for PyVMIX or a
dedicated output compositor.

Expected behavior:
- Convert trigger decisions into `LookbackClipRequest` values.
- Resolve buffer clips before switching the master output.
- Preserve manual override commands for operator control.
- Keep cooldown and maximum focus duration rules in the scheduler.
