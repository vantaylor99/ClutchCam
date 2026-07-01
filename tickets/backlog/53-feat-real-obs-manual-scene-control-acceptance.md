description: Prove the app can switch real OBS scenes only when an operator enters manual commands.
prereq: real-obs-websocket-and-scenes
files: docs/runbooks/real-obs-connection.md, ai-stream-director/src/main.py, ai-stream-director/src/obs_controller.py
difficulty: easy
----
After OBS WebSocket is enabled and the five required ClutchCam scenes exist,
run a controlled manual scene-switching acceptance pass with live transcription
and AI-driven decisions disabled.

The test should start the app with `DRY_RUN_OBS=false`, verify `/status`, then
enter a small sequence such as `/p1`, `/p2`, and `/quad`. The operator should
confirm in OBS that the current program scene changes exactly to the requested
scene and that no unexpected scene changes happen between commands.

Evidence should record:

- branch or commit under test;
- OBS host and port with password redacted;
- current OBS scene before startup;
- command sequence entered;
- app terminal output;
- observed OBS scene after each command;
- final app exit status.

This ticket should stop before real stream ingest, live transcription, and AI
switching. Those add new moving parts and belong to later tickets.
