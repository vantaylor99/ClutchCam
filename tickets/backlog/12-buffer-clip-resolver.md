description: Resolve lookback clip requests to playable media ranges
prereq: rolling-lookback-buffer
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/src/contracts.py
----
The switcher should not inspect buffer directories directly. A buffer resolver
should accept a `LookbackClipRequest` and return the concrete media files or
playlist range needed to play the target stream from before the trigger.

Expected behavior:
- Resolve clip start and end times against available rolling segments.
- Handle requests near the beginning of a stream where pre-roll is partially
  unavailable.
- Fail clearly when the requested stream or time range is no longer buffered.
- Be testable with fixture segment metadata without requiring live FFmpeg.
