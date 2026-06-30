description: Design an opt-in overlapped transcription window path so speech near audio chunk boundaries has ASR context without duplicate runtime triggers.
prereq: per-stream-transcript-utterance-assembler
files: ai-stream-director/src/services/transcription.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/config.py, ai-stream-director/tests/test_transcription_audio_extraction.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/tests/test_transcription_event_api.py, docs/ARCHITECTURE.md
difficulty: medium
----
Live transcription currently extracts fixed audio chunks, with a default
`AUDIO_EXTRACT_CHUNK_SECONDS` of 5 seconds. Fixed non-overlapping chunks are
simple and latency-friendly, but they can remove acoustic context from the ASR
model at the exact point where a word or phrase crosses a chunk boundary.

Design an opt-in mode that gives the ASR model a small amount of audio overlap
across adjacent transcription requests while still emitting clean, monotonic
runtime `TranscriptEvent` objects to the orchestrator.

## Current code notes

- `FFmpegAudioExtractor.build_ffmpeg_command(...)` currently uses the FFmpeg
  segment muxer with `-segment_time <chunk_duration>` and writes numbered files
  like `%09d.wav`.
- `CompletedAudioChunkDiscovery` treats each stable file as one completed chunk
  and infers `AudioInputRef.starts_at_seconds` from
  `int(chunk_path.stem) * chunk_duration_seconds`.
- `FasterWhisperTranscriber` offsets segment timestamps by
  `AudioInputRef.starts_at_seconds`.
- `TranscriptionRuntimePump` currently emits every final event returned by the
  transcriber; overlap-aware de-duplication does not exist below the
  orchestrator.
- The already-completed utterance assembler and prefilter duplicate window help
  reduce repeated AI calls, but the transcription worker should still avoid
  emitting repeated overlap-only transcript events.

## Design direction to evaluate

Prefer a request-window layer after chunk discovery instead of trying to make
the current FFmpeg segment muxer produce overlapping files directly.

One likely shape:

- Keep the extraction stride and chunk filenames stable so health checks,
  failure reporting, and media timeline inference remain understandable.
- Add config for transcription request overlap, separate from chunk stride,
  with validation that `0 <= overlap < AUDIO_EXTRACT_CHUNK_SECONDS`.
- For overlap disabled, keep the current `AudioInputRef` path unchanged.
- For overlap enabled, build the ASR request window from the previous stable
  chunk tail plus the current stable chunk, with `starts_at_seconds` set to the
  true media timestamp for the beginning of the request window.
- Track a per-request "new audio begins at" threshold so the runtime pump can
  drop overlap-only transcript events while preserving events that span the
  boundary.
- Keep transcript event timestamps on the stream media timeline so lookback clip
  requests continue to anchor correctly.
- Document the latency and backend-cost tradeoff, since overlap increases audio
  sent to the transcription backend.

## Edge cases & interactions

- First chunk for a stream has no previous chunk and should behave as
  non-overlapped.
- Missing, deleted, or unreadable previous chunks should fall back to the
  current chunk without failing the worker.
- Overlap must not be equal to or greater than the chunk stride.
- Duplicate filtering must be per stream and must not drop a phrase that starts
  in the overlap but ends in the new chunk.
- Text-only ASR responses without segment timestamps are risky with overlap
  because the whole response maps to the request window; the design should
  decide whether to keep, reject, or conservatively gate those responses.
- OpenAI-compatible uploads require local files, so any composed overlap window
  must have a local URI and deterministic cleanup behavior.
- Fixture and test extractors should not require FFmpeg to exercise the
  timestamp and de-duplication rules.

## Expected output of this plan stage

Emit one or more implement tickets that settle the exact implementation shape.
If the final approach needs audio composition, keep it sized so one agent can
finish it safely, and split overlap-event de-duplication into a prerequisite if
that reduces risk.
