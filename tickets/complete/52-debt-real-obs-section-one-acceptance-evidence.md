description: Completed acceptance evidence checklist for the real OBS checkpoint
prereq: feat-real-obs-connection-preflight, debt-real-obs-env-connectivity-runbook
files: docs/runbooks/real-obs-connection.md, docs/runbooks/README.md, docs/runbooks/local-linux-compose.md, ai-stream-director/README.md
----
Completed the section-one evidence checklist for the real OBS connection-only
checkpoint.

What changed:

- Captured the exact evidence operators should record: branch or commit,
  machine and runtime shape, OBS host and port with the password redacted,
  OBS version, scene state before and after the check, required scene list and
  per-scene status, the non-destructive preflight output, and an optional
  app startup/status/quit run.
- Split the preflight from the optional full orchestrator path so the checklist
  makes it clear that the preflight must not switch scenes.
- Documented the expected scene-change behavior when the full orchestrator is
  run with real OBS: the configured default scene on startup is expected, but
  no extra scene changes are.
- Linked the checklist into the shared OBS runbook and the operator docs so it
  is easy to follow from either the app README or the Compose runbook.

Validation:

- `git diff --check`

No code or tests were changed for this docs-only ticket.
