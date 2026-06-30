description: Investigate streaming or VAD-based transcription utterance boundaries
prereq: runtime-transcription-event-source
files: ai-stream-director/src/services/transcription.py, ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/contracts.py, docs/ARCHITECTURE.md, docs/ROADMAP.md
----
Fixed-duration audio chunks are a pragmatic first live-transcription boundary,
but they are not the best long-term representation of player speech. A streaming
or voice-activity-detection-aware transcription path could finalize utterances
around speech pauses instead of arbitrary wall-clock cutoffs, reducing missed
phrases and improving trigger timing.

The desired behavior is a future transcription boundary that can emit finalized
utterance-level `TranscriptEvent` values with reliable media timestamps, while
keeping the orchestrator isolated from provider-specific streaming APIs.

Expected behavior:
- The transcription service boundary can support utterance-final events without
  forcing the orchestrator to know whether they came from fixed chunks,
  overlapped chunks, or a streaming provider.
- Final utterances are based on speech activity, provider finalization signals,
  or both, rather than only fixed elapsed seconds.
- Partial transcript events may be available for diagnostics or future UI, but
  switching decisions continue to use finalized text unless explicitly changed.
- Word-level or segment-level timestamps are preserved when available so trigger
  anchors can become more precise than "end of chunk."
- The implementation remains fail-soft: unavailable streaming/VAD support should
  not break the existing fixed-chunk transcription mode.
- Live validation should compare missed trigger phrases, duplicate triggers,
  latency, and backend cost against the current fixed-chunk path.
