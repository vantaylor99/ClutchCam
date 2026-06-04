description: Keep terminal prompts and async scheduler logs readable
prereq: 
files: ai-stream-director/src/main.py, ai-stream-director/src/scheduler.py, ai-stream-director/tests/test_dry_run_obs.py
----
The terminal input loop currently lives in `main.py` through
`read_terminal_input(...)`, which calls `input("> ")` on a background thread.
Scheduler and AI logs print from the main loop while that prompt may be visible,
so background output can visually concatenate with partially entered commands.
One local dry-run session showed `/quitAI decision...`, which made it unclear
whether `/quit` was submitted or mixed with async output.

Expected behavior:

- Background scheduler and AI logs should not concatenate with user-entered
  commands.
- Async output such as AI decisions, cooldown messages, focus timeout, and
  manual scene changes should leave the terminal in a readable state.
- `/quit` should still shut down predictably when typed on its own line.
- The non-blocking terminal loop should continue allowing scheduler timers to
  advance while waiting for input.

Implementation notes:

- There is no `ai-stream-director/src/terminal_input.py` today despite the
  source fix ticket naming one. Either keep the fix in `main.py` or introduce a
  small terminal I/O helper if it materially simplifies coordination.
- Prefer a narrowly scoped output helper or prompt-refresh behavior over a
  broad terminal UI rewrite.
- Keep tests deterministic; avoid tests that require a real interactive
  terminal.

TODO:

- Add focused tests around `/quit` and async/log output behavior where feasible.
- Update terminal output handling so background logs are visually separated from
  prompts.
- Confirm manual commands and scheduler timers still work in dry-run tests.
- Run targeted dry-run tests and the full unit suite.
- Move this ticket to `review/` with validation notes.
