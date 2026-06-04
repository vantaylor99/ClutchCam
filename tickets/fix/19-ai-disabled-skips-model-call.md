description: Skip AI model calls when AI mode is disabled
prereq: 
files: ai-stream-director/src/main.py, ai-stream-director/src/scheduler.py, ai-stream-director/tests/test_dry_run_obs.py
----
When `/ai off` is active, the terminal MVP currently still accepts transcript
lines, calls the AI director, logs a model decision, and only then ignores the
result because AI mode is disabled.

Expected behavior:

- Transcript lines may still be accepted into recent context while AI mode is
  disabled.
- The app should not call Ollama/Gemma while AI mode is disabled.
- The terminal output should clearly say that AI evaluation was skipped because
  AI mode is off.
- Re-enabling AI with `/ai on` should resume the normal decision path.
- Tests should prove no model call is made while AI mode is disabled.
