description: Implement the FFmpeg rolling lookback buffer service
prereq: production-service-boundaries
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/src/config.py, ai-stream-director/src/contracts.py, ai-stream-director/src/services/buffer.py, ai-stream-director/tests/test_service_boundaries.py, ai-stream-director/tests/test_rolling_buffer.py
----
Implement the first concrete rolling lookback buffer behind the existing
`services.buffer` boundary. The implementation should retain playable media for
stable stream IDs `player_1` through `player_4`, keep the buffer rooted at the
environment-derived `LOOKBACK_BUFFER_DIR`, and resolve `LookbackClipRequest`
ranges into concrete local media references without requiring the orchestrator
or switcher to inspect the filesystem directly.

The first pass should use simple FFmpeg segmenting and filesystem metadata. It
should remain import-safe: importing `services.buffer` must not start FFmpeg,
touch the network, create buffer directories, or depend on non-standard Python
packages. Runtime work should only happen after constructing and starting the
concrete buffer service.

Recommended shape:

- Keep the existing `LookbackBuffer`, `ClipResolution`, and
  `ClipResolutionStatus` contract compatible with current callers.
- Add small buffer-specific dataclasses as needed, such as
  `SegmentRecord`, `RollingBufferConfig`, and an optional `segment_uris` field
  on `ClipResolution` so ready results can identify the exact segment files that
  cover the request.
- Add a concrete adapter such as `FFmpegRollingLookbackBuffer` or
  `SegmentedLookbackBuffer` that owns per-stream segment directories under
  `<LOOKBACK_BUFFER_DIR>/<stream_id>/`.
- Validate stream IDs against `config.STREAM_IDS`; unknown streams should return
  an unavailable result or raise a buffer setup error before any subprocess is
  launched.
- Treat request times as seconds in the same monotonic stream timeline as the
  segment metadata. Do not mix media PTS, wall-clock epoch time, and transcript
  timestamps without an explicit conversion boundary.

FFmpeg behavior:

- Prefer the HLS or segment muxer with short segments, copy codecs where
  possible, and write playable `.ts` segments plus an inspectable playlist or
  metadata sidecar per stream.
- Build the FFmpeg command from configuration rather than hardcoding host paths.
  Include configurable values for buffer root, segment duration, retention
  window, FFmpeg executable, and input URLs.
- Keep deletion bounded by `LOOKBACK_WINDOW_SECONDS`, with enough segment slack
  to avoid deleting the earliest segment needed for a request at
  `trigger_time_seconds - SWITCH_LOOKBACK_SECONDS`.
- On restart, rehydrate enough segment metadata from the stream directory or
  sidecar file to resolve already-buffered media; stale files outside retention
  may be pruned.
- Surface subprocess startup failure, early process exit, missing input URLs,
  and unwritable buffer directories through `LookbackBufferError` or clear
  unavailable/pending clip results.

Clip resolution:

- `resolve_clip(request)` should select the ordered segments that overlap the
  request's `start_time_seconds` through `end_time_seconds`.
- Return `ClipResolution.ready(...)` only when the selected segments cover the
  requested range closely enough to be usable. It is acceptable for the resolved
  start/end to snap outward to segment boundaries; include those actual bounds
  in the result.
- Return `pending` when the requested end is newer than the latest known segment
  but still plausibly inside the active stream.
- Return `unavailable` for unknown streams, missing metadata, gaps, and ranges
  older than the retained window.
- The ready result should expose a playable `media_uri`, such as a generated
  clip playlist or local file URI, and the concrete segment file URIs used to
  satisfy the request.

Fixture mode:

- Provide a deterministic fixture or dry-run buffer implementation that accepts
  synthetic `SegmentRecord` values and small temp files. Tests must not require
  live RTMP/SRT input or an installed FFmpeg binary.
- Add tests for at least these cases:
  - valid `player_1` through `player_4` stream IDs are accepted and unknown IDs
    fail clearly;
  - retention pruning removes expired segments and keeps enough recent media;
  - a request at `trigger_time_seconds - SWITCH_LOOKBACK_SECONDS` resolves to
    ordered segment files when the range is buffered;
  - gaps or ranges outside retention return unavailable;
  - a request ending just beyond the latest segment returns pending;
  - importing `services.buffer` remains side-effect free.

Documentation should be updated only where it clarifies implemented behavior:
describe the new buffer service, relevant environment variables, Linux
`/dev/shm/clutchcam` usage, fixture mode, and local validation steps.

TODO:

- Implement segment metadata and clip-resolution logic in
  `ai-stream-director/src/services/buffer.py` or a small helper module imported
  by it.
- Add the concrete FFmpeg command builder and lifecycle methods without doing
  work at import time.
- Add fixture-mode tests in `ai-stream-director/tests/test_rolling_buffer.py`
  and extend boundary tests if the public contract changes.
- Update docs/readme status notes for the implemented rolling buffer.
- Run `python -m unittest discover -s tests -v` from `ai-stream-director/`.
