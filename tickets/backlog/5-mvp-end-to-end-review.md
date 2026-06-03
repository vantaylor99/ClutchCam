description: Review and validate the AI Stream Director MVP end to end
prereq: nonblocking-terminal-loop, local-smoke-test-mode, ollama-readiness-and-json-hardening, obs-connection-and-scene-validation
files: ai-stream-director/
----
Perform a final MVP review after the local control loop, dry-run mode, Ollama checks, and OBS scene validation are implemented.

This ticket is intentionally parked in `backlog/` until the implementation tickets have moved through the pipeline. Promote it to `review/` only after the implementation work exists.

The review should focus on whether the app is understandable, testable, and ready for a first real OBS trial.

Validation should include dry-run testing and, if OBS is available, a real OBS WebSocket scene-switching test.

TODO
- Review code clarity and module boundaries.
- Verify README setup instructions against the actual app behavior.
- Run dry-run tests for calm transcript input, exciting player moments, cooldown behavior, manual overrides, `/ai off`, `/ai on`, `/status`, and `/quit`.
- Verify focus scenes return to `Quad View` without extra terminal input.
- If possible, run a live OBS test with the five expected manually created scenes.
- Move the ticket to `complete/` with testing notes and any remaining risks.
