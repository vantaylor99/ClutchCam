description: Design and implement the FFmpeg rolling lookback buffer service
prereq: production-service-boundaries
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/src/contracts.py, ai-stream-director/src/config.py
----
The buffer service retains playable media for each active stream in a rolling
window, backed by a Linux RAM disk such as `/dev/shm/clutchcam`. The service
must accept stream identities that match the orchestrator's stream IDs
(`player_1` through `player_4`) and expose clip ranges that satisfy
`LookbackClipRequest`.

The first implementation should favor simple FFmpeg segmenting over clever
media graph management. It should be restartable, inspectable from the
filesystem, and configurable through environment variables rather than hardcoded
host paths.

Expected behavior:
- Maintain at least `LOOKBACK_WINDOW_SECONDS` of recent media per stream.
- Delete or overwrite expired segments without growing beyond the retention
  budget.
- Allow a clip request at `trigger_time - SWITCH_LOOKBACK_SECONDS` to resolve to
  concrete segment files.
- Run locally on Linux with buffer storage under `/dev/shm`.
- Provide a dry-run or fixture mode for tests that does not require live RTMP or
  SRT input.
