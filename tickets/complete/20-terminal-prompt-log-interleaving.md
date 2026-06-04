description: Completed terminal prompt/log readability for dry-run MVP
prereq:
files: ai-stream-director/src/main.py, ai-stream-director/src/scheduler.py, ai-stream-director/src/obs_controller.py, ai-stream-director/tests/test_dry_run_obs.py
----
Terminal output now routes through a small prompt-aware logger during the
interactive run, so async AI, scheduler, and dry-run OBS messages land on fresh
lines instead of being visually glued to the active `> ` input prompt.

Built:

- Added `TerminalOutput` in `main.py`.
- After the input thread starts, app-side logs begin on a fresh line and refresh
  the `> ` prompt marker.
- `process_line(...)` and `handle_command(...)` accept an optional log callable,
  preserving default `print` behavior for tests and direct use.
- `SceneScheduler`, `OBSController`, and `DryRunOBSController` accept optional
  log callables and default to `print`.
- `main()` wires one `TerminalOutput.log` instance into the scheduler and OBS
  controllers so async AI, scheduler, and dry-run scene messages share the same
  terminal behavior.
- `/status` emits one multi-line status block so it refreshes the prompt once.
- Added deterministic tests for prompt-refresh formatting and `/quit` using the
  supplied terminal logger.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_dry_run_obs -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest discover -s tests -v
git diff --check
```

Result:

- Targeted dry-run tests: 19 passed.
- Full Python unit suite: 78 passed.
- `git diff --check`: passed; only CRLF normalization warnings were reported.
