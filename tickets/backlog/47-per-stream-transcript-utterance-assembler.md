description: Add per-stream transcript utterance assembly before trigger evaluation
prereq: transcript-prefilter-recent-context-boundaries
files: ai-stream-director/src/contracts.py, ai-stream-director/src/transcript_router.py, ai-stream-director/src/services/ai.py, ai-stream-director/src/main.py, ai-stream-director/tests/test_runtime_event_pipeline.py, ai-stream-director/tests/test_transcription_event_api.py
----
Provider transcript segments are not guaranteed to be natural sentences. A
single spoken thought may arrive as several short final events, or a single
fixed audio chunk may become one broad text blob. Treating each provider segment
as the semantic unit for trigger detection makes the system overly sensitive to
ASR and chunk boundaries.

The desired behavior is a small per-stream utterance assembly layer that can
represent recent speech as bounded utterance candidates before prefilter and AI
evaluation. The assembler should preserve the original transcript events, but
offer a more natural text window based on stream identity, event timing, short
silences, punctuation when available, and maximum duration limits.

Expected behavior:
- Consecutive final transcript events from the same stream can be evaluated as a
  single utterance candidate when their time gap is short.
- Long pauses, stream changes, and configured maximum utterance duration split
  candidates cleanly.
- The AI context remains readable and ordered, without silently discarding the
  original event timestamps.
- Trigger phrases split across event boundaries are detected without requiring
  the transcription provider to return sentence-perfect segments.
- Very long or repetitive ASR output is bounded so it cannot create oversized
  prompts or repeated switch attempts.
- Terminal/manual transcript input keeps working through the same router path.
