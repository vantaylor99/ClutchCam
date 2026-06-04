description: Completed lookback clip request resolution to playable media ranges
prereq: rolling-lookback-buffer
files: ai-stream-director/src/services/buffer.py, ai-stream-director/tests/test_rolling_buffer.py, docs/ROADMAP.md
----
The buffer clip resolver work is already present in the rolling lookback buffer
implementation.

Completed behavior:

- `services.buffer.LookbackBuffer` defines the resolver protocol.
- `SegmentedLookbackBuffer.resolve_clip(...)` accepts `LookbackClipRequest` and
  returns `ClipResolution` values with `ready`, `pending`, or `unavailable`
  status.
- Ready clip resolutions include a generated local HLS playlist URI and exact
  segment file URIs.
- Requests near missing, expired, gapped, unknown, or not-yet-complete media
  fail or pend with clear reasons.
- `FixtureLookbackBuffer` and `SegmentRecord` support deterministic tests without
  live FFmpeg, SRS, Docker, or OBS.
- `FFmpegRollingLookbackBuffer.resolve_clip(...)` refreshes segment metadata and
  prunes retention before resolving clips.

Validation already lives in the rolling buffer suite:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_rolling_buffer -v
```

This ticket was retired from backlog because its expected behavior has landed
under the completed rolling-lookback-buffer work.
