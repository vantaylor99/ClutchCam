description: Add an opt-in transcription overlap mode so speech at audio chunk boundaries keeps context without sending duplicate transcript events downstream.
prereq: per-stream-transcript-utterance-assembler
files: ai-stream-director/src/config.py, ai-stream-director/src/services/transcription.py, ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/README.md, docs/ARCHITECTURE.md, ai-stream-director/tests/test_transcription_audio_extraction.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/tests/test_transcription_runtime.py, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/tests/test_linux_compose_stack.py, ai-stream-director/tests/test_runtime_healthcheck_entrypoints.py
difficulty: medium
----
Implemented and reviewed opt-in overlapped transcription request windows for local WAV chunks.

The implementation adds `TRANSCRIPTION_REQUEST_OVERLAP_SECONDS`, validates it against the audio chunk duration and WAV-only composition requirement, builds composed request WAVs under `<AUDIO_EXTRACT_DIR>/_overlap/<stream_id>/`, and marks overlapped `AudioInputRef` values with `emit_from_seconds` so the runtime can drop transcript events that end entirely in the previous chunk tail. Non-overlapped transcription keeps the existing path and text-only responses still work. Overlapped requests require timestamped transcription segments so duplicate overlap-only text can be rejected safely.

Documentation and Compose examples now include the new setting. The worker keeps composed overlap files long enough for the current pump pass and removes stale composed files on later discovery passes.

## Review findings

- Checked the implementation diff from commit `1a98f5a` because the exact numbered grep pattern did not match; the implementation commit was `ticket(implement): overlapped-transcription-audio-windows`.
- Reviewed config validation, WAV window composition, local file URI handling, discovery wrapping and cleanup, runtime overlap filtering, OpenAI-compatible upload behavior, text-only response rejection, Compose configuration, and README/architecture documentation.
- No minor findings were found that required an inline patch.
- No major findings were found that required a new ticket.
- No conditional tripwires were added; the reviewed behavior is covered by existing code paths and tests rather than a future-only concern.

Validation run from `ai-stream-director/`:

```powershell
python -m unittest tests.test_transcription_audio_extraction tests.test_transcription_worker_entrypoint tests.test_transcription_runtime tests.test_transcription_event_api tests.test_linux_compose_stack -v
python -m unittest discover -s tests -v
```

Results:

- Focused suite: 74 tests passed.
- Full suite: 312 tests passed.
