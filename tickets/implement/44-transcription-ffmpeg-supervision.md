description: Make live audio extraction resilient to late and reconnecting streams
prereq: docker-runtime-ffmpeg, transcription-worker-runtime-entrypoint
files: ai-stream-director/src/transcription_worker.py, ai-stream-director/src/services/transcription.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/tests/test_transcription_audio_extraction.py
----
The FFmpeg audio extractor has the same one-shot child-process lifecycle the
rolling buffer used to have: a stream that is absent at startup or disconnects
later can leave the Python transcription worker alive without producing new
chunks. This does not block generated-ingest validation, but it must be fixed
before live transcription is considered restartable.

Expected behavior:

- Audio extraction begins when a configured stream appears after worker start.
- Exited FFmpeg children restart with bounded backoff and useful diagnostics.
- Healthy streams continue extracting while another stream reconnects.
- Worker shutdown terminates active children and interrupts recovery waits.
- Tests prove restart throttling, stream isolation, and cleanup behavior without
  requiring real FFmpeg or media inputs.

TODO:

- Refactor `FFmpegAudioExtractor` to supervise one FFmpeg child per stream with
  bounded restart backoff.
- Preserve the current command builder, output chunk layout, and
  `AudioExtractionSession` surface.
- Add tests mirroring the rolling-buffer supervision cases: late input, repeated
  failures, stable-runtime backoff reset, stream isolation, and shutdown cleanup.
- Ensure `TranscriptionWorker.run_forever()` still starts and stops the
  extractor cleanly.

