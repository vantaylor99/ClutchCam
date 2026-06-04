description: Completed buffer-backed switch target resolution
prereq: buffer-clip-resolver, gemma-orchestration-adapter
files: ai-stream-director/src/contracts.py, ai-stream-director/src/services/switcher.py, ai-stream-director/tests/test_buffered_switcher.py, ai-stream-director/tests/test_service_boundaries.py, ai-stream-director/README.md, docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md
----
Buffered switching now has a service-level boundary that can resolve lookback
clip requests before an output switch.

Completed behavior:

- `SwitcherTarget` can carry a resolved buffered `media_uri`.
- `services.switcher.build_buffered_target(...)` converts stream, scene, trigger
  time, pre-roll, and post-roll values into a `LookbackClipRequest`.
- `services.switcher.buffered_target_from_signal(...)` converts a
  stream-focused `HypeSignal` into a buffered switch target using the configured
  player scene names.
- `BufferBackedSwitcher` accepts a `LookbackBuffer`, resolves the target's clip
  request, and returns `SwitchResult` values with `applied`, `pending`, or
  `rejected` status.
- Ready clips expose the resolved playlist URI on the returned target and can be
  passed to a downstream scene switcher.
- Pending and rejected clips return clear reasons and do not call downstream
  switchers.
- `SceneOutputSwitcher` provides a generic immediate scene-switch adapter for
  OBS/PyVMIX-like controllers without importing either runtime client.
- Existing terminal MVP immediate scene switching, manual override, cooldown,
  focus duration, and return-to-quad behavior remain unchanged.

The OBS-specific media-source adapter is intentionally left for a follow-up
ticket. That adapter must set or preload an OBS media source from the ready
buffered media URI, wait for it to be playable, and then perform the program cut
without breaking the scheduler's manual override, cooldown, and focus timer
rules.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_buffered_switcher tests.test_service_boundaries tests.test_dry_run_obs -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest discover -s tests -v
```

Focused buffered-switcher validation passed 49 tests, and full discovery passed
162 tests.
