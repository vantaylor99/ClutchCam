description: Supervised FFmpeg audio extraction restarts
prereq: docker-runtime-ffmpeg, transcription-worker-runtime-entrypoint
files: ai-stream-director/src/services/transcription.py, ai-stream-director/tests/test_transcription_audio_extraction.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py
----
`FFmpegAudioExtractor` now supervises one FFmpeg child per configured stream
instead of treating extraction as a one-shot startup action. The existing
command builder, per-stream output chunk layout, and `AudioExtractionSession`
shape are preserved.

What changed:

- Launch failures and exited FFmpeg children restart with capped exponential
  backoff.
- A stable runtime resets consecutive failure backoff.
- Shutdown interrupts pending restart waits and terminates active children,
  escalating to kill after the configured timeout.
- Process diagnostics redact configured input URLs.
- Stream supervision is isolated so one stream's failure does not restart
  healthy streams.

Validation:

- `python -m unittest tests.test_transcription_audio_extraction tests.test_transcription_worker_entrypoint tests.test_transcription_runtime tests.test_transcription_event_api -v`
  - passed as part of focused validation.
- `python -m unittest discover -s tests -v`
  - `259` tests passed.
