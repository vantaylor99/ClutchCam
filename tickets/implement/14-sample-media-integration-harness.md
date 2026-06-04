description: Build deterministic sample media and transcript integration harness
prereq: rolling-lookback-buffer, transcription-event-api, buffered-switcher-playback
files: ai-stream-director/src/contracts.py, ai-stream-director/src/services/buffer.py, ai-stream-director/src/services/switcher.py, ai-stream-director/src/transcript_router.py, ai-stream-director/tests/test_sample_media_integration.py, docs/ROADMAP.md
----
Build a repeatable integration harness that exercises the current production
boundaries without live players, Docker, OBS, FFmpeg, cloud services, or a human
typing transcript lines.

The harness should simulate a known trigger phrase at a known timestamp,
preserve stream identity through transcript routing or event contracts, build a
buffered switch target, resolve it against fixture lookback media, and verify
the resulting clip begins before the trigger.

Implementation scope:

- Use small deterministic files generated inside temporary test directories
  rather than committing bulky media assets.
- Prefer existing `FixtureLookbackBuffer`, `SegmentRecord`, `TranscriptEvent`,
  `HypeSignal`, and `BufferBackedSwitcher` boundaries.
- Keep any slow or real-media path opt-in. The default unit suite must remain
  fast and must not require live media tools.
- Do not require OBS, PyVMIX, Docker, FFmpeg, Faster-Whisper, Ollama, or network
  access.
- Add focused tests proving the integration path can resolve a clip that starts
  `SWITCH_LOOKBACK_SECONDS` before a known trigger.
- Add at least one negative case for missing media or a non-trigger transcript.

TODO:

- Add `tests/test_sample_media_integration.py` with a happy-path fixture
  covering transcript event, hype signal, buffer resolution, and switch result.
- Add a negative integration case for missing/insufficient media or no accepted
  trigger.
- Reuse existing service boundaries instead of adding a new runtime dependency.
- Run:
  `python -B -m unittest tests.test_sample_media_integration tests.test_buffered_switcher tests.test_service_boundaries -v`.
