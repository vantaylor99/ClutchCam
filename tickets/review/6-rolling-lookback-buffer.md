description: Review the FFmpeg rolling lookback buffer implementation
prereq: production-service-boundaries
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/src/config.py, ai-stream-director/src/contracts.py, ai-stream-director/src/services/buffer.py, ai-stream-director/tests/test_service_boundaries.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_rolling_buffer.py
----
The first concrete rolling lookback buffer is implemented behind
`services.buffer`.

Implemented behavior:

- `SegmentRecord`, `RollingBufferConfig`, and `segment_uris` on
  `ClipResolution` describe concrete media segments while keeping the existing
  ready/pending/unavailable result contract compatible with current callers.
- `SegmentedLookbackBuffer` resolves `LookbackClipRequest` ranges against
  ordered segment metadata, detects gaps, prunes retention, returns pending for
  near-future active-stream ranges, and writes per-request local `.m3u8`
  playlists for ready clips.
- `FixtureLookbackBuffer` accepts synthetic segment records and small local temp
  files so tests do not require live RTMP/SRT input or FFmpeg.
- `FFmpegRollingLookbackBuffer` validates stable stream IDs, rehydrates
  `segments.csv`, prunes stale `.ts` files, builds one configured FFmpeg
  segment-muxer command per stream, and starts/stops subprocesses only through
  explicit lifecycle methods.
- `config.py` now exposes `LOOKBACK_SEGMENT_SECONDS`, `FFMPEG_EXECUTABLE`, and
  per-stream `LOOKBACK_INPUT_URL_PLAYER_1` through
  `LOOKBACK_INPUT_URL_PLAYER_4` overrides. Missing overrides default to
  `<INGEST_API_URL>/<stream_id>`.
- Docs describe the implemented buffer service, `/dev/shm/clutchcam` usage,
  fixture mode, environment variables, and local validation commands.

Review focus:

- Confirm the resolver's coverage and pending/unavailable thresholds match the
  intended monotonic stream timeline semantics.
- Confirm FFmpeg segment-muxer arguments are suitable for local RTMP/SRT inputs
  and produce usable `.ts` segments plus a live CSV sidecar.
- Confirm retention pruning keeps enough segment slack for
  `trigger_time_seconds - SWITCH_LOOKBACK_SECONDS` requests while remaining
  bounded.
- Confirm generated clip playlists and `segment_uris` provide enough media
  detail for the future buffered switcher without exposing filesystem traversal
  to orchestrator code.

Validation:

- PASS: `python -m unittest tests.test_contracts tests.test_service_boundaries tests.test_rolling_buffer -v`
- PASS: `python -m unittest tests.test_rolling_buffer -v`
- ATTEMPTED: `python -m unittest discover -s tests -v`
  - Blocked in this local environment because `requests` is not installed, so
    existing modules `test_ai_director` and `test_dry_run_obs` fail during
    import before their tests run.

Notes for the reviewer:

- The buffer module remains import-safe. Tests include a clean-process import
  check that verifies importing `services.buffer` does not create the configured
  lookback directory.
- This implementation is not yet wired into the live terminal MVP or OBS
  switching path; that remains Phase 4 buffered-switching work.
