description: Complete review for non-blocking terminal loop for scheduler ticks
prereq:
files: ai-stream-director/src/main.py, ai-stream-director/README.md
----
Review completed for the terminal input loop change.

The implementation keeps OBS, scheduler, transcript, and AI work on the main thread while moving blocking terminal reads into a daemon input thread. The main loop calls `scheduler.tick()` before each bounded queue wait, so scene timers continue to advance while no terminal input is submitted.

Manual commands still route through the existing command table and handlers:

- `/quad`
- `/p1`
- `/p2`
- `/p3`
- `/p4`
- `/ai on`
- `/ai off`
- `/status`
- `/quit`

Transcript lines still parse through `TranscriptRouter.parse_line()` and, when accepted, call the AI director before handing the resulting decision to the scheduler. Blank lines remain ignored and invalid transcript formats still print the existing parse guidance.

Exit behavior was reviewed for `/quit`, queued terminal EOF, and `KeyboardInterrupt`. Each path returns cleanly with the existing `Exiting.` message.

Documentation in `ai-stream-director/README.md` now notes that the terminal prompt runs separately from scheduler ticks, so scene timers continue while the app waits for transcript lines or manual commands.

Validation:

- `git diff --check -- ai-stream-director/src/main.py ai-stream-director/README.md` passed.
- Static review of `ai-stream-director/src/main.py`, `ai-stream-director/src/scheduler.py`, and `ai-stream-director/src/transcript_router.py` found no blocking issues for the ticketed behavior.
- Runtime compile/test validation could not be run in this shell because `python`, `py`, `python3`, `pytest`, and `docker` are not installed on PATH.
