description: Build sample media fixtures and end-to-end integration harness
prereq: rolling-lookback-buffer, transcription-event-api
files: docs/ROADMAP.md, ai-stream-director/tests/
----
The project needs repeatable integration tests that do not depend on live
players, OBS, or a human typing transcript lines. Sample media and transcript
fixtures should exercise ingest, buffering, transcription routing, AI decisions,
and switch requests.

Expected behavior:
- Generate or store small sample media fixtures suitable for CI.
- Simulate a trigger phrase at a known timestamp.
- Verify the resulting clip request starts before the trigger.
- Keep long-running media tests opt-in if they are too slow for every agent run.
