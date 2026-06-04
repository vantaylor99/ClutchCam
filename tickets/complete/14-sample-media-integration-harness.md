description: Completed deterministic sample media and transcript integration harness
prereq: rolling-lookback-buffer, transcription-event-api, buffered-switcher-playback
files: ai-stream-director/tests/test_sample_media_integration.py, ai-stream-director/src/contracts.py, ai-stream-director/src/services/buffer.py, ai-stream-director/src/services/switcher.py, ai-stream-director/src/transcript_router.py
----
The repo now has a deterministic no-real-media integration harness for the
sample media flow.

Completed behavior:

- The harness generates tiny segment files inside temporary directories instead
  of committing media fixtures.
- A known transcript trigger routes through `TranscriptRouter`, classifies via
  `TranscriptTriggerPrefilter`, builds a buffered target from the resulting
  `HypeSignal`, and resolves it through `FixtureLookbackBuffer` plus
  `BufferBackedSwitcher`.
- The happy path verifies an applied switch result with a buffered playlist URI,
  segment URIs, and a clip request that starts `SWITCH_LOOKBACK_SECONDS` before
  the trigger.
- A non-trigger transcript produces no hype signal and no switch target.
- A valid trigger with insufficient retained media is rejected without a media
  URI.
- The default path does not require OBS, PyVMIX, Docker, FFmpeg,
  Faster-Whisper, Ollama, network access, or bulky committed fixtures.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_sample_media_integration tests.test_buffered_switcher tests.test_service_boundaries -v
```

Focused validation passed 27 tests.
