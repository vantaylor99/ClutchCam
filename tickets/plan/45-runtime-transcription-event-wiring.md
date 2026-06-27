description: Wire live transcription events into the runtime director path
prereq: transcription-ffmpeg-supervision
files: ai-stream-director/src/transcription_worker.py, ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/main.py, ai-stream-director/src/transcript_router.py, ai-stream-director/src/services/switcher.py, ai-stream-director/tests/test_runtime_event_pipeline.py, docs/runbooks/local-linux-compose.md
----
Once audio extraction is supervised, the next product step is connecting live
transcription output to the director pipeline so terminal text is no longer the
only trigger source.

The target runtime path is:

```text
audio chunks -> Faster-Whisper -> TranscriptEvent -> RuntimeTranscriptEventHandler
  -> local prefilter -> AI director -> scheduler/switch target
```

Expected behavior:

- Normalized `TranscriptEvent` values preserve stream identity, timestamps, and
  final/partial status.
- The existing transcript router and AI director consume live transcript events
  without changing the terminal MVP command path.
- AI-disabled mode, cooldown gating, and local prefilter behavior remain
  consistent between terminal input and live transcription input.
- The first integrated runtime can run in dry-run OBS mode before real OBS
  playback is validated.
- Buffered switch targets remain optional until OBS media-source runtime
  injection is deliberately enabled.

Open design points:

- Whether `transcription-worker` should emit JSON lines to an orchestrator
  process, write to a local queue, or run in-process for the next local
  checkpoint.
- Whether partial transcript events should update context immediately or only
  final events should be eligible for AI decisions.
- How much backpressure or deduplication is needed between chunk transcription
  and AI classification.

