description: Completed /ai off terminal skip before AI director model calls
prereq:
files: ai-stream-director/src/main.py, ai-stream-director/tests/test_dry_run_obs.py
----
The terminal transcript path now skips Gemma/Ollama model evaluation before
calling `AIDirector.decide()` when `/ai off` is active.

Built:

- `main.process_line()` still parses and records accepted transcript lines.
- After parse success, it checks `scheduler.status().ai_enabled`.
- When AI mode is off, it prints that AI evaluation was skipped and returns
  without building model context or calling the director.
- When AI mode is on, the existing model decision path is preserved.
- `SceneScheduler.apply_ai_decision()` remains a defensive guard for non-terminal
  callers.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_dry_run_obs -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest discover -s tests -v
git diff --check
```

Result:

- Targeted dry-run tests: 15 passed.
- Full Python unit suite: 74 passed.
- `git diff --check`: passed; only CRLF normalization warnings were reported.
