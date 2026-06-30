description: Explore overlapped audio windows for chunk-boundary ASR quality
prereq: per-stream-transcript-utterance-assembler
files: ai-stream-director/src/services/transcription.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/config.py, ai-stream-director/tests/test_transcription_audio_extraction.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/tests/test_transcription_event_api.py, docs/ARCHITECTURE.md
----
Live transcription currently extracts fixed audio chunks, with a default
`AUDIO_EXTRACT_CHUNK_SECONDS` of 5 seconds. Fixed non-overlapping chunks are
simple and latency-friendly, but they can remove acoustic context from the ASR
model at the exact point where a word or phrase crosses a chunk boundary.

The desired behavior is an opt-in transcription mode that gives the ASR model a
small amount of overlap across adjacent audio windows while still emitting
clean, monotonic runtime `TranscriptEvent` objects to the orchestrator.

Expected behavior:
- The default non-overlapped mode remains available until live validation proves
  the overlapped mode is better.
- Operators can configure overlap separately from the transcription request
  stride, with validation that prevents nonsensical values.
- Transcript events emitted from overlapped audio are de-duplicated so repeated
  speech in the overlap does not create repeated local triggers or AI calls.
- Event timestamps continue to map back to the stream media timeline used by
  buffered clips.
- Chunk discovery, worker health, and failure reporting remain understandable
  when overlapping windows are enabled.
- The design accounts for CPU/GPU cost and latency, since overlap increases the
  amount of audio sent to the transcription backend.
