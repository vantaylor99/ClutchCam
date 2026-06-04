description: Add a transcription worker runtime entrypoint
prereq: transcription-runtime-pump
files: ai-stream-director/src/transcription_worker.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py
----
The repo has audio extraction, a Faster-Whisper-compatible adapter, and an
active ticket for a reusable transcription runtime pump. After that pump lands,
add a worker entrypoint that can run as its own local Linux process or Compose
service without depending on terminal input.

The worker should load `AppConfig`, start `FFmpegAudioExtractor`, feed extracted
`AudioInputRef` values through the reusable pump and
`FasterWhisperTranscriber`, and emit normalized transcript events or accepted
router messages through an explicit sink. The first sink can be JSON lines on
stdout so the runtime path is observable before the orchestrator subscribes to
it. Do not wire this worker into `src/main.py` in this ticket.

Runtime expectations:

- Audio chunks default to `AUDIO_EXTRACT_DIR=/dev/shm/clutchcam-audio`.
- Input URLs follow `AUDIO_INPUT_URL_*`, then `LOOKBACK_INPUT_URL_*`, then
  `<INGEST_API_URL>/<stream_id>` through existing config behavior.
- `TRANSCRIPTION_API_URL` may point to a local container or a remote
  Faster-Whisper-compatible endpoint.
- A slow, unavailable, or malformed transcription endpoint should be surfaced
  per audio chunk without crashing healthy streams unless fail-fast mode is
  explicitly requested.

Tests should avoid live FFmpeg, Docker, SRS, and network calls. Use fake
extractors, fake transcribers, temporary chunk paths, and captured stdout.

TODO:

- Add `src/transcription_worker.py` with an import-safe main function and
  `if __name__ == "__main__"` entrypoint.
- Construct `AudioExtractionConfig` and `FasterWhisperTranscriber` from
  `AppConfig` without duplicating environment parsing.
- Start and stop `FFmpegAudioExtractor` with signal-safe cleanup.
- Poll or otherwise discover completed audio chunks without reprocessing the
  same file repeatedly.
- Feed discovered chunks through the reusable transcription runtime pump from
  `transcription-runtime-pump`.
- Emit normalized transcript events or accepted router messages as structured
  JSON lines on stdout.
- Add tests for startup config, de-duplication of processed chunks, per-chunk
  failure isolation, stdout event shape, and signal-safe cleanup.
- Run focused tests with bytecode disabled:
  `python -B -m unittest tests.test_transcription_worker_entrypoint tests.test_transcription_runtime tests.test_transcription_event_api -v`.
