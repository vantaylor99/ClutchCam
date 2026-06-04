description: Completed reusable transcription runtime pump
prereq: transcription-event-api
files: ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/tests/test_transcription_runtime.py, ai-stream-director/tests/test_transcription_event_api.py
----
Added a reusable, standard-library-only transcription runtime pump that turns
`AudioInputRef` values into routed `TranscriptEvent` values.

Built:

- Added `services.transcription_runtime`.
- Added `TranscriptionRuntimePump.run_once(...)` for one-shot fixture and future
  runtime processing.
- Added `run_transcription_pump(...)` convenience helper.
- Added a sink protocol shaped like `TranscriptRouter.add_event(...)`.
- Added summary counters for processed audio refs, emitted transcript events,
  accepted events, rejected events, and isolated per-audio-ref failures.
- Kept transcription and sink failures isolated by default, with fail-fast mode
  available for startup validation.
- Added tests for successful router emission, router rejection counting,
  `TranscriptionError` isolation, malformed output isolation, fail-fast behavior,
  and `None` output validation.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_transcription_runtime tests.test_transcription_event_api -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest discover -s tests -v
git diff --check
```

Result:

- Focused transcription runtime/API suite: 16 tests passed.
- Full Python unit suite: 93 tests passed.
- `git diff --check`: passed; only CRLF normalization warnings were reported.
