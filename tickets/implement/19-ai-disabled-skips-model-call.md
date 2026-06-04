description: Skip Gemma/Ollama model evaluation while terminal AI mode is off
prereq:
files: ai-stream-director/src/main.py, ai-stream-director/src/scheduler.py, ai-stream-director/src/transcript_router.py, ai-stream-director/src/ai_director.py, ai-stream-director/tests/test_dry_run_obs.py
----
The terminal MVP supports `/ai off` through `SceneScheduler.set_ai_enabled(False)`,
but disabled AI mode is currently enforced too late in the transcript path.

Current call path:

- `main.process_line()` treats non-command input as transcript text.
- `TranscriptRouter.parse_line()` validates the line and appends it to recent
  history.
- `process_line()` prints that it is asking the AI director, builds recent
  context, and calls `ai_director.decide(context)`.
- Only after the model returns does `SceneScheduler.apply_ai_decision()` check
  `self.ai_enabled` and print `AI decision ignored because AI mode is off.`

That prevents scene switches while AI mode is disabled, but it still sends every
accepted transcript line to Gemma/Ollama. The AI-enabled guard needs to happen
before the director call while preserving transcript history updates.

Expected behavior:

- Transcript lines are still accepted into `TranscriptRouter` history while
  `/ai off` is active.
- `AIDirector.decide()` is not called while `scheduler.status().ai_enabled` is
  false.
- Terminal output clearly says AI evaluation was skipped because AI mode is off,
  and should not say it is asking the AI director in the skipped path.
- `/ai on` resumes the normal path: accepted transcript lines build recent
  context, call the director, print the model decision, and apply the scheduler
  decision.
- Existing `SceneScheduler.apply_ai_decision()` behavior can remain as a
  defensive guard for callers outside the terminal transcript path.

Reproducing test/spec notes:

- Add a unit test around `main.process_line()` using a real `TranscriptRouter`,
  a `SceneScheduler` with `DryRunOBSController`, and a mocked AI director.
- Arrange the scheduler with `set_ai_enabled(False)`, then call
  `process_line("player_2: no way, I found diamonds", ...)`.
- Assert the return value is `False`, `ai_director.decide` was not called, and
  `transcript_router.get_recent_context_text()` contains the accepted
  `player_2` line.
- Capture stdout and assert it mentions that AI evaluation was skipped because
  AI mode is off. Also assert the skipped path does not print the normal
  `Asking AI director` wording.
- Add a paired enabled-mode assertion or extend an existing process-line test so
  that when AI is on, the same path still calls `ai_director.decide()` once and
  passes the resulting `DirectorDecision` to scheduler logic.

Implementation notes:

The smallest fix is likely in `main.process_line()` after successful transcript
parsing and before building context or calling `ai_director.decide()`. Query the
scheduler's current AI-enabled state there, print the skip message if disabled,
and return without asking the director. Keep the parse step before this guard so
recent context continues to accumulate for the next `/ai on` decision.

TODO:

- Add the disabled-mode reproducer for `process_line()` in
  `ai-stream-director/tests/test_dry_run_obs.py` or a focused terminal main test
  module matching the current unittest style.
- Add or preserve enabled-mode coverage proving `AIDirector.decide()` still runs
  when AI mode is on.
- Update `ai-stream-director/src/main.py` so accepted transcript lines skip the
  director call before model context construction when AI mode is off.
- Keep `SceneScheduler.apply_ai_decision()` as a defensive final guard unless a
  broader scheduler contract change is deliberately made.
- Run focused unittest coverage with bytecode disabled, for example
  `python -B -m unittest tests.test_dry_run_obs -v`, after dependencies are
  available in the active Python environment.
