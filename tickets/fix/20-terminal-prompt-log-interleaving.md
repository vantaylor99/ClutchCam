description: Keep terminal prompts and async scheduler logs readable
prereq: 
files: ai-stream-director/src/main.py, ai-stream-director/src/terminal_input.py, ai-stream-director/src/scheduler.py, ai-stream-director/tests/test_dry_run_obs.py
----
During local dry-run testing, async AI/scheduler logs can visually collide with
the input prompt. One observed line rendered as `/quitAI decision...`, making it
unclear whether the command was submitted, ignored, or mixed with background
output.

Expected behavior:

- Background scheduler and AI logs should not concatenate with user-entered
  commands.
- After async output such as focus timeout or manual scene changes, the terminal
  should return to a clear input state.
- `/quit` should be easy to enter and should shut down predictably when typed on
  its own line.
- The existing non-blocking terminal loop should keep scheduler timers running.
