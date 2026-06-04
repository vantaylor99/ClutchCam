description: Completed transcription worker runtime entrypoint
prereq: transcription-runtime-pump
files: ai-stream-director/src/transcription_worker.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py
----
The transcription stack now has an import-safe runtime entrypoint at
`ai-stream-director/src/transcription_worker.py`.

Built:

- Added `build_worker(...)` using `AppConfig`,
  `AudioExtractionConfig.from_app_config`, `FFmpegAudioExtractor`,
  `FasterWhisperTranscriber.from_app_config`, and the reusable
  `TranscriptionRuntimePump`.
- Added `CompletedAudioChunkDiscovery` to discover stable completed chunks under
  `<AUDIO_EXTRACT_DIR>/<stream_id>/*.<container>` exactly once.
- Added numeric FFmpeg segment-name start-time inference for chunks such as
  `000000002.wav`.
- Added `TranscriptionWorker` lifecycle ownership so extraction starts, chunks
  are pumped, failures remain per-chunk, and extraction always stops in
  `finally`.
- Added stop-only SIGINT/SIGTERM handling through `SignalStopController`.
- Added a first JSON-lines stdout sink for transcript events and transcription
  failures.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_transcription_worker_entrypoint tests.test_transcription_runtime tests.test_transcription_event_api -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_ai_director tests.test_dry_run_obs tests.test_buffer_worker_entrypoint tests.test_rolling_buffer tests.test_transcription_worker_entrypoint tests.test_transcription_runtime tests.test_transcription_event_api tests.test_telemetry tests.test_service_boundaries -v
```

Result:

- Focused transcription worker/runtime/API suite: 21 tests passed.
- Combined review suite: 93 tests passed.
